from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from nodes.agent_node import Node as AgentNode
from nodes.codex_node import Node as CodexNode
from scripts.long_task_benchmark_artifacts import EventJournal
from scripts.long_task_benchmark_artifacts import git_workspace_snapshot
from scripts.long_task_benchmark_artifacts import require_empty_result_dir
from scripts.long_task_benchmark_artifacts import resolve_agent_profile


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _agent_config(profile_path: Path, workspace: Path, node_id: str) -> dict[str, Any]:
    profile = _read_json(profile_path)
    fields = profile.get("fields")
    if not isinstance(fields, dict):
        raise ValueError(f"Agent profile has no fields object: {profile_path}")
    config = dict(fields)
    config.update(
        {
            "node_id": node_id,
            "type_id": "agent_node",
            "name": node_id,
            "graph_id": "benchmark",
            "working_path": str(workspace),
        }
    )
    return config


def _codex_config(provider_id: str, workspace: Path, node_id: str) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "type_id": "codex_node",
        "name": node_id,
        "graph_id": "benchmark",
        "working_path": str(workspace),
        "provider_id": provider_id,
        "instruction": "",
        "codex_command": "codex",
        "sandbox": "danger-full-access",
        "reasoning_effort": "high",
        "web_search": "live",
    }


def _notice_payload(event: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(str(event.get("message") or ""))
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def summarize_events(events: list[dict[str, Any]], *, duration_ms: int, output: str) -> dict[str, Any]:
    summaries: dict[int, dict[str, Any]] = {}
    completions: dict[int, dict[str, Any]] = {}
    tool_starts = 0
    tool_ends = 0
    failed_tools = 0
    thinking_chars = 0
    gateway_requests: list[dict[str, Any]] = []
    for record in events:
        event = record.get("event")
        if not isinstance(event, dict):
            continue
        event_type = str(event.get("type") or "")
        if event_type == "tool_call_start":
            tool_starts += 1
        elif event_type == "tool_call_end":
            tool_ends += 1
            if str(event.get("status") or "") not in {"", "completed", "success"}:
                failed_tools += 1
        elif event_type == "node_thinking_delta":
            thinking_chars += len(str(event.get("delta") or ""))
        if event_type != "runtime_notice":
            continue
        stage = str(event.get("stage") or "")
        payload = _notice_payload(event)
        if stage == "provider_gateway_request":
            gateway_requests.append(payload)
            continue
        try:
            request_index = int(payload.get("request_index"))
        except (TypeError, ValueError):
            continue
        if stage == "provider_request_summary":
            summaries[request_index] = payload
        elif stage == "provider_request_completed":
            completions[request_index] = payload

    usage_totals = {
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "cached_input_tokens": 0,
        "cache_write_input_tokens": 0,
        "reasoning_output_tokens": 0,
    }
    usage_request_count = 0
    requests: list[dict[str, Any]] = []
    for request_index in sorted(set(summaries) | set(completions)):
        summary = summaries.get(request_index) or {}
        completion = completions.get(request_index) or {}
        usage = completion.get("usage")
        usage = usage if isinstance(usage, dict) else {}
        if usage:
            usage_request_count += 1
        for key in usage_totals:
            try:
                usage_totals[key] += max(0, int(usage.get(key) or 0))
            except (TypeError, ValueError):
                pass
        requests.append(
            {
                "request_index": request_index,
                "responses_mode": str(summary.get("responses_mode") or ""),
                "approx_input_chars": int(summary.get("approx_input_chars") or 0),
                "approx_input_tokens": int(summary.get("approx_input_tokens") or 0),
                "tools_included_count": int(summary.get("tools_included_count") or 0),
                "usage": usage,
            }
        )
    return {
        "duration_ms": max(0, int(duration_ms)),
        "output_chars": len(output),
        "model_turn_count": len(completions),
        "usage_model_turn_count": usage_request_count,
        "missing_usage_model_turn_count": max(0, len(completions) - usage_request_count),
        "tool_call_start_count": tool_starts,
        "tool_call_end_count": tool_ends,
        "failed_tool_call_count": failed_tools,
        "thinking_chars": thinking_chars,
        "usage": usage_totals,
        "requests": requests,
        "provider_gateway_requests": gateway_requests,
    }


def run_benchmark(args: argparse.Namespace) -> dict[str, Any]:
    workspace = Path(args.workspace).resolve()
    prompt_path = Path(args.prompt_file).resolve()
    result_dir = Path(args.result_dir).resolve()
    if not workspace.is_dir():
        raise ValueError(f"Workspace does not exist: {workspace}")
    require_empty_result_dir(result_dir)
    journal = EventJournal(result_dir / "events.jsonl")
    workspace_before = git_workspace_snapshot(workspace)
    prompt = prompt_path.read_text(encoding="utf-8").strip()
    if not prompt:
        raise ValueError(f"Prompt is empty: {prompt_path}")

    node_id = f"{args.node_type.capitalize()}Bench"
    node_dir = result_dir / "node"
    node_dir.mkdir(parents=True, exist_ok=True)
    config_path = node_dir / "config.json"
    memory_path = node_dir / "memory.md"
    messages_path = node_dir / "messages.jsonl"
    if args.node_type == "agent":
        profile_path = resolve_agent_profile(args.profile, project_root=PROJECT_ROOT)
        config = _agent_config(profile_path, workspace, node_id)
        node = AgentNode()
    else:
        config = _codex_config(args.provider_id, workspace, node_id)
        node = CodexNode()
    _write_json(config_path, config)

    events: list[dict[str, Any]] = []
    started = time.monotonic()

    def capture(event: dict[str, Any]) -> None:
        record = {
            "elapsed_ms": int((time.monotonic() - started) * 1000),
            "event": dict(event),
        }
        journal.append(record)
        events.append(record)

    context = {
        "task_id": f"benchmark-{args.node_type}-{int(time.time())}",
        "graph_id": "benchmark",
        "node_instance_id": node_id,
        "node_config_path": str(config_path),
        "memory_path": str(memory_path),
        "messages_path": str(messages_path),
        "stream_callback": capture,
    }
    try:
        result = node.on_input(prompt, context)
    except Exception as exc:
        duration_ms = int((time.monotonic() - started) * 1000)
        payload = _benchmark_payload(
            args,
            config=config,
            workspace=workspace,
            prompt_path=prompt_path,
            profile_path=profile_path if args.node_type == "agent" else None,
            events=events,
            duration_ms=duration_ms,
            output="",
            status="error",
            error=f"{type(exc).__name__}: {exc}",
            workspace_before=workspace_before,
            workspace_after=git_workspace_snapshot(workspace),
        )
        _write_json(result_dir / "result.json", payload)
        raise
    duration_ms = int((time.monotonic() - started) * 1000)
    output = str(result.get("display") or "") if isinstance(result, dict) else str(result or "")
    payload = _benchmark_payload(
        args,
        config=config,
        workspace=workspace,
        prompt_path=prompt_path,
        profile_path=profile_path if args.node_type == "agent" else None,
        events=events,
        duration_ms=duration_ms,
        output=output,
        status="completed",
        workspace_before=workspace_before,
        workspace_after=git_workspace_snapshot(workspace),
    )
    _write_json(result_dir / "result.json", payload)
    return payload


def _benchmark_payload(
    args: argparse.Namespace,
    *,
    config: dict[str, Any],
    workspace: Path,
    prompt_path: Path,
    profile_path: Path | None,
    events: list[dict[str, Any]],
    duration_ms: int,
    output: str,
    status: str,
    workspace_before: dict[str, Any],
    workspace_after: dict[str, Any],
    error: str = "",
) -> dict[str, Any]:
    payload = {
        "schema_version": 2,
        "status": status,
        "node_type": args.node_type,
        "provider_id": config.get("provider_id"),
        "workspace": str(workspace),
        "prompt_file": str(prompt_path),
        "profile": str(profile_path) if profile_path is not None else "",
        "event_journal": "events.jsonl",
        "workspace_before": workspace_before,
        "workspace_after": workspace_after,
        "summary": summarize_events(events, duration_ms=duration_ms, output=output),
        "output": output,
        "events": events,
    }
    if error:
        payload["error"] = error
    return payload


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run one isolated AgentNode or Codex long-task benchmark.")
    parser.add_argument("--node-type", choices=("agent", "codex"), required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--prompt-file", required=True)
    parser.add_argument("--result-dir", required=True)
    parser.add_argument("--provider-id", default="GPT_Official")
    parser.add_argument("--profile", default=str(PROJECT_ROOT / "agent" / "GPT1.json"))
    return parser


def main() -> int:
    args = _parser().parse_args()
    try:
        result = run_benchmark(args)
    except Exception:
        raise
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
