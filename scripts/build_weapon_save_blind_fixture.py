from __future__ import annotations

import argparse
import json
from pathlib import Path


CONVERSATION_LINES = {1, 20, 23, 73, 76, 231, 234, 296}
TRACE_IDS = {
    "0450723035d54ad19887f494a5fc3e39",
    "41ad2bc738184388a9b3e5e44be1a02a",
    "95904398177f4cb5a9bdcbd821a6313f",
}
ARTIFACT_NAMES = (
    "20260803_153228_workspace_exec_call_1dff9bbf.json",
    "20260803_154440_workspace_exec_call_303d05ca.json",
    "20260803_154455_workspace_exec_call_6c0a73b1.json",
    "20260803_154509_workspace_exec_call_1eda4411.json",
)


def build_fixture(source: Path, output: Path) -> None:
    if output.exists() and any(output.iterdir()):
        raise RuntimeError(f"Fixture output is not empty: {output}")
    output.mkdir(parents=True, exist_ok=True)
    archive_messages = source / "archive" / "2026-08-03" / "messages.jsonl"
    selected_messages = []
    for line_number, line in enumerate(archive_messages.read_text(encoding="utf-8").splitlines(), start=1):
        if line_number in CONVERSATION_LINES:
            selected_messages.append(line)
    (output / "conversation-before-final-user-analysis.jsonl").write_text(
        "\n".join(selected_messages) + "\n",
        encoding="utf-8",
    )

    selected_runtime_events = []
    selected_runtime_traces: set[str] = set()
    for line in (source / "runtime_events.jsonl").read_text(encoding="utf-8").splitlines():
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            continue
        trace_id = str(record.get("trace_id") or "")
        if trace_id not in TRACE_IDS or trace_id in selected_runtime_traces:
            continue
        event = record.get("runtime_event")
        if not isinstance(event, dict):
            continue
        if str(event.get("stage") or "") == "openai_responses_request_start":
            try:
                event_payload = json.loads(str(event.get("message") or "{}"))
            except json.JSONDecodeError:
                continue
            selected_runtime_events.append(
                {
                    "ts": record.get("ts"),
                    "trace_id": record.get("trace_id"),
                    "stage": event.get("stage"),
                    "provider": event.get("provider"),
                    "request_payload_keys": sorted(event_payload),
                }
            )
            selected_runtime_traces.add(trace_id)
    (output / "selected-request-events.json").write_text(
        json.dumps(selected_runtime_events, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    operations: dict[str, dict] = {}
    for name in ARTIFACT_NAMES:
        outer = json.loads((source / "tool_artifacts" / name).read_text(encoding="utf-8"))
        content = json.loads(str(outer.get("content") or "{}"))
        for stage in content.get("stages", []):
            for operation in stage.get("operations", []):
                if isinstance(operation, dict) and str(operation.get("id") or ""):
                    operations[str(operation["id"])] = operation

    exact_log_result = operations["exact_log_windows"]["result"]
    (output / "game-log-switch-restore-windows.txt").write_text(
        str(exact_log_result.get("stdout") or ""),
        encoding="utf-8",
    )
    identity_result = operations["continue_log_context"]["result"]
    (output / "actor-identity-log-window.txt").write_text(
        str(identity_result.get("stdout") or ""),
        encoding="utf-8",
    )
    source_operation_ids = (
        "equipment_source",
        "switch_code",
        "save_code",
        "restore_code",
        "quickbar_notify_code",
        "notify_impl",
        "attach_full",
    )
    (output / "relevant-source-read-results.json").write_text(
        json.dumps(
            {operation_id: operations[operation_id]["result"] for operation_id in source_operation_ids},
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (output / "patch-diffs-at-investigation-time.txt").write_text(
        str(operations["diffs"]["result"].get("stdout") or ""),
        encoding="utf-8",
    )

    bundle_names = (
        "conversation-before-final-user-analysis.jsonl",
        "game-log-switch-restore-windows.txt",
        "actor-identity-log-window.txt",
        "relevant-source-read-results.json",
        "patch-diffs-at-investigation-time.txt",
        "selected-request-events.json",
    )
    bundle_parts = []
    for name in bundle_names:
        bundle_parts.append(f"<raw_evidence_file path=\"{name}\">\n")
        bundle_parts.append((output / name).read_text(encoding="utf-8"))
        bundle_parts.append(f"\n</raw_evidence_file path=\"{name}\">\n")
    (output / "evidence-bundle.txt").write_text("\n".join(bundle_parts), encoding="utf-8")

    manifest = {
        "schema_version": 1,
        "source": str(source),
        "conversation_source": str(archive_messages),
        "included_conversation_line_numbers": sorted(CONVERSATION_LINES),
        "excluded_conversation_from_line": 299,
        "runtime_trace_ids": sorted(TRACE_IDS),
        "raw_tool_artifact_sources": list(ARTIFACT_NAMES),
        "normalized_evidence_files": [
            "game-log-switch-restore-windows.txt",
            "actor-identity-log-window.txt",
            "relevant-source-read-results.json",
            "patch-diffs-at-investigation-time.txt",
            "selected-request-events.json",
            "evidence-bundle.txt",
        ],
        "construction_rule": (
            "Includes pre-correction conversation claims, selected original request events, "
            "and mechanically unpacked raw tool results. It excludes the later user-supplied diagnosis, "
            "task-direction ledgers, memory summaries, and all generated answer dossiers."
        ),
    }
    (output / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Build the no-answer-leak weapon-save incident fixture.")
    parser.add_argument("--source", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    build_fixture(Path(args.source).resolve(), Path(args.output).resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
