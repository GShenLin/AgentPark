from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any


TERMINAL_ERROR_STATUSES = {
    "error",
    "exception",
    "failed",
    "failure",
    "invalid_arguments",
    "timeout",
    "stopped",
    "cancellation_failed",
    "blocked",
    "locked",
    "locked_or_readonly",
    "permission_denied",
}


SUCCESS_STATUSES = {"", "ok", "done", "success", "completed"}
USER_STOPPED_TOOL_CALL_RESULT = "UserStoppedThisCall"


@dataclass(frozen=True)
class ToolExecutionResult:
    status: str
    result: Any = None
    error: str | None = None
    tool_name: str | None = None

    @property
    def ok(self) -> bool:
        return self.status not in TERMINAL_ERROR_STATUSES

    def model_output(self) -> Any:
        if self.status == "stopped" and self.result == USER_STOPPED_TOOL_CALL_RESULT:
            return USER_STOPPED_TOOL_CALL_RESULT
        if self.ok:
            return self.result
        payload = _payload_from_result(self.result)
        payload["status"] = self.status or payload.get("status") or "error"
        if self.tool_name:
            payload["tool"] = self.tool_name
        if self.error:
            payload["error"] = self.error
        return json.dumps(payload, ensure_ascii=False)


def build_success_result(result: Any, *, tool_name: str | None = None) -> ToolExecutionResult:
    status, error = status_and_error_from_payload(result)
    if status in TERMINAL_ERROR_STATUSES:
        return build_error_result(status, tool_name=tool_name, error=error, result=result)
    return ToolExecutionResult(status="completed", result=result, tool_name=tool_name)


def build_error_result(
    status: str,
    *,
    tool_name: str | None = None,
    error: str | None = None,
    result: Any = None,
) -> ToolExecutionResult:
    normalized_status = str(status or "error").strip().lower() or "error"
    return ToolExecutionResult(
        status=normalized_status,
        result=result,
        error=str(error or "").strip() or _first_error_text(result),
        tool_name=tool_name,
    )


def build_user_stopped_result(*, tool_name: str | None = None) -> ToolExecutionResult:
    return ToolExecutionResult(
        status="stopped",
        result=USER_STOPPED_TOOL_CALL_RESULT,
        error=None,
        tool_name=tool_name,
    )


def build_cancellation_failed_result(*, tool_name: str | None = None) -> ToolExecutionResult:
    return build_error_result(
        "cancellation_failed",
        tool_name=tool_name,
        error="Tool did not stop after cancellation was requested.",
    )


def normalize_tool_execution_result(value: Any, *, tool_name: str | None = None) -> ToolExecutionResult:
    if isinstance(value, ToolExecutionResult):
        return value
    status, error = status_and_error_from_payload(value)
    if status in TERMINAL_ERROR_STATUSES:
        return build_error_result(status, tool_name=tool_name, error=error, result=value)
    return build_success_result(value, tool_name=tool_name)


def status_and_error_from_payload(value: Any) -> tuple[str, str | None]:
    payload = _decode_json_object(value)
    if not isinstance(payload, dict):
        return "completed", None
    status = str(payload.get("status") or "").strip().lower()
    if status in TERMINAL_ERROR_STATUSES:
        return status, _first_error_text(payload)
    if status in SUCCESS_STATUSES:
        return "completed", None
    return "completed", None


def _first_error_text(value: Any) -> str | None:
    payload = _decode_json_object(value)
    if not isinstance(payload, dict):
        return str(value or "").strip() or None
    for key in ("error", "reason", "hint", "message"):
        item = payload.get(key)
        if item is not None and str(item).strip():
            return str(item).strip()
    return None


def _decode_json_object(value: Any) -> Any:
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            return json.loads(text)
        except Exception:
            return None
    return value


def _payload_from_result(value: Any) -> dict[str, Any]:
    payload = _decode_json_object(value)
    if isinstance(payload, dict):
        return dict(payload)
    return {}
