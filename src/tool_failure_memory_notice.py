from __future__ import annotations

from typing import Any

from src.tool.tool_execution_result import TERMINAL_ERROR_STATUSES
from src.tool_failure_companion import notify_companion_about_tool_failure_memory


class ToolFailureMemoryNoticeMixin:
    def _notify_companion_about_failed_tool_executions(self, executions: object) -> bool:
        if not bool(getattr(self, "tool_failure_memory_notice_enabled", False)):
            return False
        failures = self._collect_failed_tool_executions(executions)
        if not failures:
            return False
        return notify_companion_about_tool_failure_memory(self, failures)

    def _collect_failed_tool_executions(self, executions: object) -> list[dict[str, Any]]:
        failures: list[dict[str, Any]] = []
        for execution in executions if isinstance(executions, list) else []:
            status = self._execution_status(execution)
            if status not in TERMINAL_ERROR_STATUSES:
                continue
            failures.append(
                {
                    "tool_name": self._execution_tool_name(execution),
                    "call_id": self._execution_call_id(execution),
                    "status": status,
                    "error": self._execution_error(execution),
                    "result_preview": self._truncate(self._execution_result(execution), 1600),
                }
            )
        return failures

    @staticmethod
    def _execution_status(execution: object) -> str:
        if isinstance(execution, dict):
            return str(execution.get("status") or "").strip().lower()
        return str(getattr(execution, "status", "") or "").strip().lower()

    @staticmethod
    def _execution_tool_name(execution: object) -> str:
        if isinstance(execution, dict):
            return str(execution.get("func_name") or execution.get("tool_name") or "").strip()
        return str(getattr(execution, "func_name", "") or "").strip()

    @staticmethod
    def _execution_call_id(execution: object) -> str:
        if isinstance(execution, dict):
            return str(execution.get("call_id") or "").strip()
        return str(getattr(execution, "call_id", "") or "").strip()

    @staticmethod
    def _execution_error(execution: object) -> str:
        if isinstance(execution, dict):
            return str(execution.get("error") or "").strip()
        return str(getattr(execution, "error", "") or "").strip()

    @staticmethod
    def _execution_result(execution: object) -> str:
        if isinstance(execution, dict):
            return str(execution.get("cleaned_result") or "")
        return str(getattr(execution, "cleaned_result", "") or "")

    @staticmethod
    def _truncate(value: object, limit: int) -> str:
        text = str(value or "")
        if len(text) <= limit:
            return text
        return text[: max(0, limit - 3)].rstrip() + "..."
