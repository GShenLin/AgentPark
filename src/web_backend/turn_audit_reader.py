from __future__ import annotations

import json
import os
import re
from collections.abc import Iterable
from typing import Any

from src.tool.tool_stats_store import get_tool_calls_log_path


RUNTIME_EVENTS_FILENAME = "runtime_events.jsonl"
MESSAGES_FILENAME = "messages.jsonl"
MAX_ARTIFACT_BYTES = 5 * 1024 * 1024
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9_-]+$")
_ARTIFACT_PATH_PATTERN = re.compile(
    r"""[A-Za-z]:[\\/][^"\r\n]*?tool_artifacts[^"\r\n]*?\.(?:json|diff)""",
    re.IGNORECASE,
)


def validate_component(value: object, label: str, *, required: bool = False) -> str:
    text = str(value or "").strip()
    if not text:
        if required:
            raise ValueError(f"{label} is required")
        return ""
    if not _SAFE_COMPONENT.fullmatch(text):
        raise ValueError(f"{label} contains unsupported characters")
    return text


def iter_node_runtime_paths(
    memories_root: str,
    *,
    graph_id: str = "",
    node_id: str = "",
) -> Iterable[tuple[str, str, str]]:
    root = os.path.abspath(memories_root)
    if not os.path.isdir(root):
        return
    selected_graph = validate_component(graph_id, "graph_id")
    selected_node = validate_component(node_id, "node_id")
    for graph_name in sorted(os.listdir(root)):
        if graph_name.startswith("_") or (selected_graph and graph_name != selected_graph):
            continue
        graph_dir = os.path.join(root, graph_name)
        if not os.path.isdir(graph_dir) or not _SAFE_COMPONENT.fullmatch(graph_name):
            continue
        for node_name in sorted(os.listdir(graph_dir)):
            if selected_node and node_name != selected_node:
                continue
            node_dir = os.path.join(graph_dir, node_name)
            runtime_path = os.path.join(node_dir, RUNTIME_EVENTS_FILENAME)
            if (
                os.path.isdir(node_dir)
                and _SAFE_COMPONENT.fullmatch(node_name)
                and os.path.isfile(runtime_path)
            ):
                yield graph_name, node_name, runtime_path


def read_jsonl(path: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    if not os.path.isfile(path):
        return records
    with open(path, "rb") as handle:
        for raw_line in handle:
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(payload, dict):
                records.append(payload)
    return records


def hydrate_runtime_record(record: dict[str, Any], node_dir: str) -> dict[str, Any]:
    return _hydrate_value(record, node_dir)


def _hydrate_value(value: Any, node_dir: str) -> Any:
    if isinstance(value, list):
        return [_hydrate_value(item, node_dir) for item in value]
    if not isinstance(value, dict):
        return value
    if value.get("type") == "runtime_event_artifact":
        artifact_path = _safe_node_artifact_path(node_dir, value.get("artifact_path"))
        if not artifact_path:
            return value
        try:
            with open(artifact_path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError):
            return value
    return {str(key): _hydrate_value(child, node_dir) for key, child in value.items()}


def read_node_messages(node_dir: str, dates: Iterable[str]) -> list[dict[str, Any]]:
    paths = [os.path.join(node_dir, MESSAGES_FILENAME)]
    for date_text in sorted({str(item or "").strip() for item in dates if str(item or "").strip()}):
        paths.append(os.path.join(node_dir, "archive", date_text, MESSAGES_FILENAME))
    records: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for path in paths:
        for record in read_jsonl(path):
            record_id = str(record.get("id") or "").strip()
            if record_id and record_id in seen_ids:
                continue
            if record_id:
                seen_ids.add(record_id)
            records.append(record)
    records.sort(key=lambda item: str(item.get("created_at") or ""))
    return records


def read_tool_stats_for_calls(
    call_ids: set[str],
    *,
    tool_calls_path: str | None = None,
) -> dict[str, dict[str, Any]]:
    if not call_ids:
        return {}
    path = str(tool_calls_path or get_tool_calls_log_path())
    matches: dict[str, dict[str, Any]] = {}
    if not os.path.isfile(path):
        return matches
    with open(path, "rb") as handle:
        for raw_line in handle:
            try:
                payload = json.loads(raw_line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            call_id = str(payload.get("call_id") or "").strip()
            if call_id in call_ids:
                matches[call_id] = payload
    return matches


def extract_artifact_paths(value: Any) -> list[str]:
    paths: list[str] = []

    def visit(child: Any) -> None:
        if isinstance(child, dict):
            for key, item in child.items():
                if (
                    isinstance(item, str)
                    and str(key).lower().endswith("path")
                    and "tool_artifacts" in item.replace("\\", "/").lower()
                ):
                    paths.append(item)
                visit(item)
            return
        if isinstance(child, list):
            for item in child:
                visit(item)
            return
        if not isinstance(child, str):
            return
        text = child.strip()
        if text[:1] in {"{", "["}:
            try:
                visit(json.loads(text))
            except json.JSONDecodeError:
                pass
        paths.extend(match.group(0) for match in _ARTIFACT_PATH_PATTERN.finditer(child))

    visit(value)
    return list(dict.fromkeys(paths))


def read_tool_artifacts(node_dir: str, paths: Iterable[str]) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for raw_path in dict.fromkeys(str(item or "").strip() for item in paths):
        path = _safe_tool_artifact_path(node_dir, raw_path)
        if not path or not os.path.isfile(path):
            continue
        size = os.path.getsize(path)
        if size > MAX_ARTIFACT_BYTES:
            artifacts.append(
                {
                    "path": path,
                    "name": os.path.basename(path),
                    "size": size,
                    "content": "",
                    "too_large": True,
                }
            )
            continue
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
        except OSError:
            continue
        payload: dict[str, Any] = {
            "path": path,
            "name": os.path.basename(path),
            "size": size,
            "content": content,
            "too_large": False,
        }
        if path.lower().endswith(".json"):
            try:
                parsed = json.loads(content)
            except json.JSONDecodeError:
                parsed = None
            if isinstance(parsed, dict):
                payload["data"] = parsed
        artifacts.append(payload)
    return artifacts


def _safe_node_artifact_path(node_dir: str, raw_path: object) -> str:
    text = str(raw_path or "").strip()
    if not text:
        return ""
    candidate = text if os.path.isabs(text) else os.path.join(node_dir, text)
    return _contained_path(node_dir, candidate)


def _safe_tool_artifact_path(node_dir: str, raw_path: object) -> str:
    candidate = _safe_node_artifact_path(node_dir, raw_path)
    if not candidate:
        return ""
    tool_root = os.path.join(node_dir, "tool_artifacts")
    return _contained_path(tool_root, candidate)


def _contained_path(root: str, candidate: str) -> str:
    try:
        resolved_root = os.path.normcase(os.path.realpath(root))
        resolved_candidate = os.path.normcase(os.path.realpath(candidate))
        if os.path.commonpath([resolved_root, resolved_candidate]) != resolved_root:
            return ""
        return os.path.realpath(candidate)
    except (OSError, ValueError):
        return ""


__all__ = [
    "extract_artifact_paths",
    "hydrate_runtime_record",
    "iter_node_runtime_paths",
    "read_jsonl",
    "read_node_messages",
    "read_tool_artifacts",
    "read_tool_stats_for_calls",
    "validate_component",
]
