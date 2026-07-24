import argparse
import json
import os
import subprocess
import sys
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from src.memory_root import get_memories_root
from src.web_backend.node_config_service import node_config_service


WORKSPACE_WATCH_DIRS = (".runtime", ".cache")


@dataclass(frozen=True)
class FileState:
    size: int
    mtime_ns: int


def _run_powershell_json(script: str) -> Any:
    completed = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            script,
        ],
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or completed.stdout.strip() or "PowerShell command failed")
    text = completed.stdout.strip()
    if not text:
        return None
    return json.loads(text)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def find_fastapi_process(workspace_root: Path) -> dict[str, Any] | None:
    root_text = str(workspace_root)
    escaped = root_text.replace("'", "''")
    script = (
        "Get-CimInstance Win32_Process | "
        "Where-Object { $_.CommandLine -like '*-m src.fast_api*' "
        f"-and $_.CommandLine -like '*{escaped}*' }} | "
        "Select-Object -First 1 ProcessId,Name,CommandLine | ConvertTo-Json -Compress"
    )
    result = _run_powershell_json(script)
    if not isinstance(result, dict):
        return None
    return result


def read_process_sample(pid: int) -> dict[str, Any]:
    script = (
        "Get-CimInstance Win32_PerfFormattedData_PerfProc_Process | "
        f"Where-Object {{ $_.IDProcess -eq {int(pid)} }} | "
        "Select-Object -First 1 Name,IDProcess,IOReadBytesPersec,IOWriteBytesPersec,"
        "IODataBytesPersec,PercentProcessorTime,WorkingSet | ConvertTo-Json -Compress"
    )
    result = _run_powershell_json(script)
    if not isinstance(result, dict):
        raise RuntimeError(f"process {pid} was not found in performance counters")
    return result


def snapshot_files(workspace_root: Path) -> dict[str, FileState]:
    states: dict[str, FileState] = {}
    roots = [workspace_root / dirname for dirname in WORKSPACE_WATCH_DIRS]
    roots.append(Path(get_memories_root()))
    for root in roots:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            try:
                display_path = str(path.relative_to(workspace_root))
            except ValueError:
                display_path = str(path)
            states[display_path] = FileState(size=int(stat.st_size), mtime_ns=int(stat.st_mtime_ns))
    return states


def changed_files(
    previous: dict[str, FileState],
    current: dict[str, FileState],
    ignored_paths: set[str] | None = None,
) -> list[dict[str, Any]]:
    ignored = ignored_paths or set()
    changes: list[dict[str, Any]] = []
    for rel, state in current.items():
        if rel in ignored:
            continue
        old = previous.get(rel)
        if old is None:
            changes.append({"path": rel, "change": "created", "size": state.size, "delta_size": state.size})
            continue
        if old != state:
            changes.append(
                {
                    "path": rel,
                    "change": "modified",
                    "size": state.size,
                    "delta_size": state.size - old.size,
                }
            )
    for rel, old in previous.items():
        if rel in ignored:
            continue
        if rel not in current:
            changes.append({"path": rel, "change": "deleted", "size": 0, "delta_size": -old.size})
    changes.sort(key=lambda item: (str(item.get("path") or ""), str(item.get("change") or "")))
    return changes


def read_runtime_nodes(workspace_root: Path) -> list[dict[str, Any]]:
    memories = Path(get_memories_root())
    if not memories.is_dir():
        return []
    nodes: list[dict[str, Any]] = []
    for config_path in memories.rglob("config.json"):
        if config_path.parent == memories:
            continue
        try:
            payload = node_config_service.read_strict(str(config_path))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        pending = payload.get("pending")
        pending_count = len(pending) if isinstance(pending, list) else int(payload.get("pending_count") or 0)
        try:
            display_path = str(config_path.relative_to(workspace_root))
        except ValueError:
            display_path = str(config_path)
        nodes.append(
            {
                "path": display_path,
                "graph_id": str(payload.get("graph_id") or config_path.parent.parent.name),
                "node_id": str(payload.get("node_id") or config_path.parent.name),
                "type_id": str(payload.get("type_id") or ""),
                "state": str(payload.get("state") or ""),
                "pending_count": pending_count,
                "has_inflight": isinstance(payload.get("inflight"), dict),
                "clock_running": bool(payload.get("_clock_running")),
                "clock_remaining_seconds": payload.get("_clock_remaining_seconds"),
                "last_run_at": payload.get("last_run_at"),
                "last_message": str(payload.get("last_message") or "")[:180],
            }
        )
    return nodes


def interesting_nodes(nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for node in nodes:
        if (
            node.get("state") == "working"
            or int(node.get("pending_count") or 0) > 0
            or bool(node.get("has_inflight"))
            or bool(node.get("clock_running"))
        ):
            result.append(node)
    result.sort(key=lambda item: (str(item.get("graph_id") or ""), str(item.get("node_id") or "")))
    return result


def _mb(value: Any) -> float:
    try:
        return round(float(value or 0) / (1024 * 1024), 3)
    except (TypeError, ValueError):
        return 0.0


def collect_trace(workspace_root: Path, pid: int, duration: float, interval: float, output: Path) -> list[dict[str, Any]]:
    output.parent.mkdir(parents=True, exist_ok=True)
    samples: list[dict[str, Any]] = []
    ignored_paths: set[str] = set()
    try:
        ignored_paths.add(str(output.resolve().relative_to(workspace_root)))
    except ValueError:
        pass
    previous_files = snapshot_files(workspace_root)
    deadline = time.monotonic() + max(0.1, duration)

    with output.open("w", encoding="utf-8") as handle:
        while True:
            now = datetime.now().isoformat(timespec="milliseconds")
            process = read_process_sample(pid)
            current_files = snapshot_files(workspace_root)
            changes = changed_files(previous_files, current_files, ignored_paths=ignored_paths)
            nodes = read_runtime_nodes(workspace_root)
            sample = {
                "timestamp": now,
                "pid": pid,
                "process": {
                    "name": process.get("Name"),
                    "cpu_percent": process.get("PercentProcessorTime"),
                    "working_set_mb": _mb(process.get("WorkingSet")),
                    "io_read_mbps": _mb(process.get("IOReadBytesPersec")),
                    "io_write_mbps": _mb(process.get("IOWriteBytesPersec")),
                    "io_total_mbps": _mb(process.get("IODataBytesPersec")),
                },
                "workspace": {
                    "watched_files": len(current_files),
                    "changed_files": changes,
                },
                "runtime_nodes": interesting_nodes(nodes),
            }
            handle.write(json.dumps(sample, ensure_ascii=False) + "\n")
            handle.flush()
            samples.append(sample)
            previous_files = current_files
            if time.monotonic() >= deadline:
                break
            time.sleep(max(0.2, interval))
    return samples


def summarize(samples: list[dict[str, Any]]) -> dict[str, Any]:
    if not samples:
        return {"sample_count": 0}
    read_values = [float(s["process"]["io_read_mbps"]) for s in samples]
    write_values = [float(s["process"]["io_write_mbps"]) for s in samples]
    cpu_values = [float(s["process"]["cpu_percent"] or 0) for s in samples]
    changed_counter: Counter[str] = Counter()
    changed_delta: defaultdict[str, int] = defaultdict(int)
    node_counter: Counter[str] = Counter()

    for sample in samples:
        for item in sample["workspace"]["changed_files"]:
            path = str(item.get("path") or "")
            changed_counter[path] += 1
            changed_delta[path] += int(item.get("delta_size") or 0)
        for node in sample["runtime_nodes"]:
            key = f"{node.get('graph_id')}/{node.get('node_id')} ({node.get('type_id')})"
            node_counter[key] += 1

    return {
        "sample_count": len(samples),
        "avg_io_read_mbps": round(sum(read_values) / len(read_values), 3),
        "max_io_read_mbps": round(max(read_values), 3),
        "avg_io_write_mbps": round(sum(write_values) / len(write_values), 3),
        "max_io_write_mbps": round(max(write_values), 3),
        "avg_cpu_percent": round(sum(cpu_values) / len(cpu_values), 2),
        "max_cpu_percent": round(max(cpu_values), 2),
        "top_changed_files": [
            {"path": path, "samples_changed": count, "total_delta_size": changed_delta[path]}
            for path, count in changed_counter.most_common(20)
        ],
        "active_nodes": [
            {"node": key, "samples_seen": count}
            for key, count in node_counter.most_common(20)
        ],
    }


def write_summary(summary: dict[str, Any], output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# AgentPark Performance Diagnostic Summary",
        "",
        f"- Samples: {summary.get('sample_count', 0)}",
        f"- Avg process I/O read: {summary.get('avg_io_read_mbps', 0)} MB/s",
        f"- Max process I/O read: {summary.get('max_io_read_mbps', 0)} MB/s",
        f"- Avg process I/O write: {summary.get('avg_io_write_mbps', 0)} MB/s",
        f"- Max CPU counter: {summary.get('max_cpu_percent', 0)}",
        "",
        "## Active Nodes",
    ]
    active_nodes = summary.get("active_nodes") or []
    if active_nodes:
        for item in active_nodes:
            lines.append(f"- {item['node']}: seen in {item['samples_seen']} samples")
    else:
        lines.append("- None")

    lines.append("")
    lines.append("## Changed Files")
    changed_files = summary.get("top_changed_files") or []
    if changed_files:
        for item in changed_files:
            lines.append(
                f"- {item['path']}: changed in {item['samples_changed']} samples, "
                f"total size delta {item['total_delta_size']} bytes"
            )
    else:
        lines.append("- None")
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record AgentPark process and workspace performance diagnostics.")
    parser.add_argument("--workspace-root", default=os.getcwd())
    parser.add_argument("--pid", type=int, default=0)
    parser.add_argument("--duration", type=float, default=30.0)
    parser.add_argument("--interval", type=float, default=1.0)
    parser.add_argument("--output", default="")
    parser.add_argument("--summary-output", default="")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(list(argv or []))
    workspace_root = Path(args.workspace_root).resolve()
    if not workspace_root.is_dir():
        raise SystemExit(f"workspace root does not exist: {workspace_root}")
    pid = int(args.pid or 0)
    if pid <= 0:
        process = find_fastapi_process(workspace_root)
        if not process:
            raise SystemExit("could not find a running src.fast_api process for this workspace; pass --pid")
        pid = int(process["ProcessId"])

    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    output = Path(args.output) if args.output else workspace_root / ".runtime" / f"performance-trace-{pid}-{stamp}.jsonl"
    summary_output = (
        Path(args.summary_output)
        if args.summary_output
        else workspace_root / ".runtime" / f"performance-summary-{pid}-{stamp}.md"
    )
    samples = collect_trace(
        workspace_root=workspace_root,
        pid=pid,
        duration=float(args.duration),
        interval=float(args.interval),
        output=output,
    )
    summary = summarize(samples)
    write_summary(summary, summary_output)
    print(json.dumps({"pid": pid, "trace": str(output), "summary": str(summary_output), **summary}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
