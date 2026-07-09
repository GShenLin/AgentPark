from __future__ import annotations

import json
import math
import os
import shutil
import sys
import tempfile
import threading
from datetime import datetime
from typing import Any

from src.tool.tool_execution_result import TERMINAL_ERROR_STATUSES
from src.workspace_settings import get_workspace_cache_dir


TOOL_STATS_DIRNAME = "tool_stats"
TOOL_CALLS_LOG_FILENAME = "tool_calls.jsonl"
TOOL_STATS_SUMMARY_FILENAME = "summary.json"
TOOL_STATS_ERRORS_FILENAME = "errors.jsonl"
DEFAULT_RECENT_TOOL_CALL_LIMIT = 50

_LOCK = threading.Lock()


def get_tool_stats_dir() -> str:
    return os.path.join(get_workspace_cache_dir(), TOOL_STATS_DIRNAME)


def get_tool_calls_log_path() -> str:
    return os.path.join(get_tool_stats_dir(), TOOL_CALLS_LOG_FILENAME)


def get_tool_stats_summary_path() -> str:
    return os.path.join(get_tool_stats_dir(), TOOL_STATS_SUMMARY_FILENAME)


def get_tool_stats_error_log_path() -> str:
    return os.path.join(get_tool_stats_dir(), TOOL_STATS_ERRORS_FILENAME)


class ToolCallStatsRecorder:
    def __init__(self, *, provider_id: str, graph_id: str = "", node_id: str = "") -> None:
        self.provider_id = str(provider_id or "").strip() or "unknown"
        self.graph_id = str(graph_id or "").strip()
        self.node_id = str(node_id or "").strip()
        self._active_calls: dict[str, dict[str, Any]] = {}
        self._lock = threading.Lock()

    def handle(self, event: dict[str, Any]) -> None:
        event_type = str(event.get("type") or "").strip().lower()
        if event_type == "tool_call_start":
            call_id = str(event.get("call_id") or "").strip()
            if call_id:
                with self._lock:
                    self._active_calls[call_id] = dict(event)
            return
        if event_type != "tool_call_end":
            return

        call_id = str(event.get("call_id") or "").strip()
        if call_id:
            with self._lock:
                start_event = self._active_calls.pop(call_id, {})
        else:
            start_event = {}
        try:
            append_tool_call_stat(
                build_tool_call_stat_record(
                    provider_id=self.provider_id,
                    graph_id=self.graph_id,
                    node_id=self.node_id,
                    start_event=start_event,
                    end_event=event,
                )
            )
        except Exception as exc:
            _record_tool_stats_error("recorder_handle", exc, {"event": event})


def build_tool_call_stat_record(
    *,
    provider_id: str,
    graph_id: str = "",
    node_id: str = "",
    start_event: dict[str, Any] | None = None,
    end_event: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start = start_event if isinstance(start_event, dict) else {}
    end = end_event if isinstance(end_event, dict) else {}
    status = str(end.get("status") or "completed").strip().lower() or "completed"
    success = status not in TERMINAL_ERROR_STATUSES
    tool_name = str(end.get("name") or start.get("name") or "tool").strip() or "tool"
    call_id = str(end.get("call_id") or start.get("call_id") or "").strip()

    record = {
        "recorded_at": _now_iso(),
        "provider_id": str(provider_id or "").strip() or "unknown",
        "graph_id": str(graph_id or "").strip(),
        "node_id": str(node_id or "").strip(),
        "tool_name": tool_name,
        "call_id": call_id,
        "success": success,
        "status": status,
        "error": str(end.get("error") or "").strip(),
        "duration_ms": end.get("duration_ms") if isinstance(end.get("duration_ms"), int) else None,
        "started_at": str(start.get("event_time") or "").strip(),
        "completed_at": str(end.get("event_time") or "").strip(),
        "agent_event_provider": str(end.get("provider") or start.get("provider") or "").strip(),
        "tool_call_raw": start.get("raw_call"),
        "tool_call_arguments": start.get("arguments") if isinstance(start.get("arguments"), dict) else None,
        "tool_call_arguments_json": str(start.get("arguments_json") or "").strip(),
        "result": end.get("result"),
        "result_preview": str(end.get("result_preview") or "").strip(),
        "result_chars": end.get("result_chars") if isinstance(end.get("result_chars"), int) else None,
        "diagnostics": [str(item) for item in end.get("diagnostics")]
        if isinstance(end.get("diagnostics"), list)
        else [],
    }
    return _json_compatible(record)


def append_tool_call_stat(record: dict[str, Any]) -> None:
    if not isinstance(record, dict):
        raise ValueError("tool call stat record must be an object")
    payload = _json_compatible(record)
    with _LOCK:
        stats_dir = get_tool_stats_dir()
        os.makedirs(stats_dir, exist_ok=True)
        with open(get_tool_calls_log_path(), "a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            handle.write("\n")
        try:
            summary = _load_summary_unlocked()
            _apply_record_to_summary(summary, payload)
            _write_summary_unlocked(summary)
        except Exception as exc:
            _write_tool_stats_error_unlocked(
                "summary_update",
                exc,
                {"provider_id": payload.get("provider_id"), "tool_name": payload.get("tool_name")},
            )


def load_tool_stats_summary() -> dict[str, Any]:
    with _LOCK:
        return _load_summary_unlocked()


def clear_tool_stats() -> None:
    with _LOCK:
        for path in (get_tool_calls_log_path(), get_tool_stats_summary_path(), get_tool_stats_error_log_path()):
            try:
                os.remove(path)
            except FileNotFoundError:
                continue


def load_recent_tool_call_stats(limit: int = DEFAULT_RECENT_TOOL_CALL_LIMIT) -> list[dict[str, Any]]:
    try:
        safe_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise ValueError("recent tool call limit must be an integer") from exc
    if safe_limit <= 0:
        return []

    path = get_tool_calls_log_path()
    if not os.path.isfile(path):
        return []

    with _LOCK:
        with open(path, "r", encoding="utf-8") as handle:
            lines = handle.readlines()

    records: list[dict[str, Any]] = []
    for line in lines[-safe_limit:]:
        text = line.strip()
        if not text:
            continue
        payload = json.loads(text)
        if not isinstance(payload, dict):
            raise ValueError("tool call log record must contain an object")
        records.append(payload)
    records.reverse()
    return records


def _load_summary_unlocked() -> dict[str, Any]:
    path = get_tool_stats_summary_path()
    if not os.path.isfile(path):
        return {"providers": {}}
    with open(path, "r", encoding="utf-8") as handle:
        try:
            payload = json.load(handle)
        except json.JSONDecodeError as exc:
            archive_path = _preserve_corrupt_summary_unlocked(path, exc)
            _write_tool_stats_error_unlocked(
                "summary_recovery",
                exc,
                {"summary_path": path, "archive_path": archive_path},
            )
            return {"providers": {}}
    if not isinstance(payload, dict):
        raise ValueError("tool stats summary must contain a top-level object")
    providers = payload.get("providers")
    if not isinstance(providers, dict):
        payload["providers"] = {}
    return payload


def _write_summary_unlocked(summary: dict[str, Any]) -> None:
    path = get_tool_stats_summary_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix="summary.", suffix=".tmp", dir=os.path.dirname(path), text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(summary, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def _preserve_corrupt_summary_unlocked(path: str, exc: json.JSONDecodeError) -> str:
    archive_path = _unique_corrupt_summary_path(path)
    try:
        shutil.copy2(path, archive_path)
        return archive_path
    except Exception as copy_exc:
        _write_tool_stats_error_unlocked(
            "summary_recovery_archive",
            copy_exc,
            {"summary_path": path, "json_error": str(exc)},
        )
        return ""


def _unique_corrupt_summary_path(path: str) -> str:
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    base = f"{path}.corrupt-{stamp}"
    candidate = base
    index = 1
    while os.path.exists(candidate):
        candidate = f"{base}.{index}"
        index += 1
    return candidate


def _record_tool_stats_error(stage: str, exc: Exception, context: dict[str, Any] | None = None) -> None:
    try:
        with _LOCK:
            _write_tool_stats_error_unlocked(stage, exc, context or {})
    except Exception as log_exc:
        _write_tool_stats_stderr(stage, log_exc)


def _write_tool_stats_error_unlocked(
    stage: str,
    exc: Exception,
    context: dict[str, Any] | None = None,
) -> None:
    record = {
        "recorded_at": _now_iso(),
        "stage": str(stage or "tool_stats").strip() or "tool_stats",
        "error_type": type(exc).__name__,
        "error": str(exc),
        "context": _json_compatible(context or {}),
    }
    path = get_tool_stats_error_log_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True))
        handle.write("\n")


def _write_tool_stats_stderr(stage: str, exc: Exception) -> None:
    print(f"[tool_stats] failed to record {stage} error: {type(exc).__name__}: {exc}", file=sys.stderr)


def _apply_record_to_summary(summary: dict[str, Any], record: dict[str, Any]) -> None:
    provider_id = str(record.get("provider_id") or "unknown").strip() or "unknown"
    tool_name = str(record.get("tool_name") or "tool").strip() or "tool"
    status = str(record.get("status") or "completed").strip().lower() or "completed"
    success = bool(record.get("success"))
    now = _now_iso()

    providers = summary.setdefault("providers", {})
    if not isinstance(providers, dict):
        raise ValueError("tool stats summary providers must be an object")
    provider = providers.setdefault(
        provider_id,
        {
            "provider_id": provider_id,
            "total": 0,
            "success": 0,
            "failure": 0,
            "statuses": {},
            "tools": {},
            "last_call_at": "",
        },
    )
    _increment_counter(provider, success=success, status=status)
    provider["last_call_at"] = now

    tools = provider.setdefault("tools", {})
    if not isinstance(tools, dict):
        raise ValueError(f"tool stats summary provider {provider_id!r} tools must be an object")
    tool = tools.setdefault(
        tool_name,
        {
            "tool_name": tool_name,
            "total": 0,
            "success": 0,
            "failure": 0,
            "statuses": {},
            "last_call_at": "",
            "last_status": "",
            "last_error": "",
            "last_result_preview": "",
        },
    )
    _increment_counter(tool, success=success, status=status)
    tool["last_call_at"] = now
    tool["last_status"] = status
    tool["last_error"] = str(record.get("error") or "").strip()
    tool["last_result_preview"] = str(record.get("result_preview") or "").strip()
    summary["updated_at"] = now


def _increment_counter(target: dict[str, Any], *, success: bool, status: str) -> None:
    target["total"] = int(target.get("total") or 0) + 1
    key = "success" if success else "failure"
    target[key] = int(target.get(key) or 0) + 1
    other = "failure" if success else "success"
    target[other] = int(target.get(other) or 0)
    statuses = target.setdefault("statuses", {})
    if not isinstance(statuses, dict):
        raise ValueError("tool stats summary statuses must be an object")
    statuses[status] = int(statuses.get(status) or 0) + 1


def _json_compatible(value: Any) -> Any:
    if value is None or isinstance(value, (str, bool, int)):
        return value
    if isinstance(value, float):
        return value if math.isfinite(value) else str(value)
    if isinstance(value, dict):
        return {str(key): _json_compatible(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_compatible(item) for item in value]
    try:
        json.dumps(value, ensure_ascii=False, allow_nan=False)
        return value
    except (TypeError, ValueError):
        return str(value)


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
