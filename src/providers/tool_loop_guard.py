from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass
from typing import Any

from src.tool.tool_call_protocol import ToolCallEnvelope
from src.tool.tool_call_protocol import ToolCallExecution
from src.tool.tool_call_protocol import ensure_json_text


LOOP_GUARDED_TOOLS = {"rg_list_files", "rg_search_text"}


@dataclass(frozen=True)
class ToolLoopDecision:
    blocked: bool
    reason: str = ""
    policy: str = "repeated_tool_signature_guard"
    signature: str = ""
    repeat_count: int = 0
    previous_call_id: str = ""


class ToolLoopGuard:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._history: list[dict[str, Any]] = []

    def inspect_and_record(self, call: ToolCallEnvelope) -> ToolLoopDecision:
        if not isinstance(call, ToolCallEnvelope):
            return ToolLoopDecision(blocked=False)
        tool_name = str(call.name or "").strip()
        if tool_name not in LOOP_GUARDED_TOOLS:
            return ToolLoopDecision(blocked=False)

        entry = _history_entry(call)
        with self._lock:
            decision = self._decision_for_entry(entry)
            self._history.append(entry)
            self._history = self._history[-24:]
        return decision

    def _decision_for_entry(self, entry: dict[str, Any]) -> ToolLoopDecision:
        for previous in reversed(self._history):
            if previous.get("signature") == entry.get("signature"):
                return ToolLoopDecision(
                    blocked=True,
                    reason="The same rg tool call was already attempted in this turn.",
                    signature=str(entry.get("signature") or ""),
                    repeat_count=1,
                    previous_call_id=str(previous.get("call_id") or ""),
                )
            if _is_max_results_only_broader_repeat(previous, entry):
                return ToolLoopDecision(
                    blocked=True,
                    reason="The rg tool call only increases max_results after an earlier equivalent call.",
                    signature=str(entry.get("signature_without_max_results") or ""),
                    repeat_count=1,
                    previous_call_id=str(previous.get("call_id") or ""),
                )
            if _is_search_glob_broader_repeat(previous, entry):
                return ToolLoopDecision(
                    blocked=True,
                    reason="The rg search repeats the same query and root with broader include_globs.",
                    signature=str(entry.get("query_root_signature") or ""),
                    repeat_count=1,
                    previous_call_id=str(previous.get("call_id") or ""),
                )
        return ToolLoopDecision(blocked=False)


def build_tool_loop_blocked_execution(call: ToolCallEnvelope, decision: ToolLoopDecision) -> ToolCallExecution:
    payload = {
        "status": "blocked",
        "retryable": False,
        "policy": decision.policy,
        "tool": call.name,
        "call_id": call.call_id,
        "previous_call_id": decision.previous_call_id,
        "reason": decision.reason,
        "signature": decision.signature,
        "instruction": (
            "Do not repeat the same broad rg call. Summarize the evidence already collected, "
            "use a narrower include_globs/query, read a specific file, or ask the user for direction."
        ),
    }
    return ToolCallExecution(
        func_name=call.name,
        call_id=call.call_id,
        cleaned_result=ensure_json_text(payload),
        image_data=None,
        status="blocked",
        error=decision.reason,
        diagnostics=(decision.policy,),
    )


def _history_entry(call: ToolCallEnvelope) -> dict[str, Any]:
    normalized_args = _normalize_args(call.arguments)
    without_max = dict(normalized_args)
    without_max.pop("max_results", None)
    return {
        "tool": call.name,
        "call_id": call.call_id,
        "arguments": normalized_args,
        "signature": _stable_json({"tool": call.name, "arguments": normalized_args}),
        "signature_without_max_results": _stable_json({"tool": call.name, "arguments": without_max}),
        "query_root_signature": _stable_json(
            {
                "tool": call.name,
                "query": normalized_args.get("query", ""),
                "project_root": normalized_args.get("project_root", ""),
            }
        ),
    }


def _normalize_args(args: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {}
    for key, value in (args or {}).items():
        if key in {"include_globs", "exclude_globs"}:
            normalized[key] = sorted(
                {str(item or "").replace("\\", "/").strip() for item in value or [] if str(item or "").strip()}
            )
        elif key == "project_root":
            text = str(value or "").strip()
            normalized[key] = os.path.normcase(os.path.abspath(text)) if text else ""
        elif key == "max_results":
            try:
                normalized[key] = int(value)
            except Exception:
                normalized[key] = value
        else:
            normalized[key] = value
    return normalized


def _stable_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _is_max_results_only_broader_repeat(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if previous.get("tool") != current.get("tool"):
        return False
    if previous.get("signature_without_max_results") != current.get("signature_without_max_results"):
        return False
    previous_max = _as_int((previous.get("arguments") or {}).get("max_results"))
    current_max = _as_int((current.get("arguments") or {}).get("max_results"))
    return current_max is not None and previous_max is not None and current_max >= previous_max


def _is_search_glob_broader_repeat(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    if previous.get("tool") != "rg_search_text" or current.get("tool") != "rg_search_text":
        return False
    previous_args = previous.get("arguments") or {}
    current_args = current.get("arguments") or {}
    if previous_args.get("query") != current_args.get("query"):
        return False
    if previous_args.get("project_root", "") != current_args.get("project_root", ""):
        return False
    previous_globs = previous_args.get("include_globs") or []
    current_globs = current_args.get("include_globs") or []
    return bool(previous_globs) and _is_broad_glob_set(current_globs)


def _is_broad_glob_set(globs: list[str]) -> bool:
    if not globs:
        return True
    broad = {"*", "**", "**/*", "*.*", "**/*.*"}
    return all(str(item or "").strip().replace("\\", "/").strip("./") in broad for item in globs)


def _as_int(value: Any) -> int | None:
    try:
        return int(value)
    except Exception:
        return None
