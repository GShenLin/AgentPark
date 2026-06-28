from __future__ import annotations

import json
from typing import Any

from src.operational_memory import operational_memory_path_for_agent
from src.operational_memory import operational_memory_snapshot
from src.tool.tool_execution_result import TERMINAL_ERROR_STATUSES


class OperationalMemoryGateMixin:
    def _run_operational_memory_gate_for_failed_executions(self, executions: object) -> bool:
        if not bool(getattr(self, "operational_memory_gate_enabled", False)):
            return False
        if bool(getattr(self, "_operational_memory_gate_active", False)):
            return False
        failures = self._collect_failed_tool_executions(executions)
        if not failures:
            return False

        had_memory_tool = "record_operational_memory" in self.tools.function_map
        previous_memory_tool = self.tools.function_map.get("record_operational_memory")
        declaration = self._ensure_operational_memory_tool_registered()
        prompt = self._build_operational_memory_gate_prompt(failures)
        self.Message("system", prompt, persist=False)

        previous = bool(getattr(self, "_operational_memory_gate_active", False))
        start_index = len(getattr(self, "messages", []) or [])
        self._operational_memory_gate_active = True
        try:
            for attempt in range(2):
                self._send_operational_memory_gate_once(declaration)
                if self._has_operational_memory_tool_call_since(start_index):
                    return self._has_operational_memory_record_since(start_index)
                if attempt == 0:
                    self.Message("system", self._build_operational_memory_gate_missing_tool_feedback(), persist=False)
            return False
        finally:
            if had_memory_tool:
                self.tools.function_map["record_operational_memory"] = previous_memory_tool
            else:
                self.tools.function_map.pop("record_operational_memory", None)
            self._operational_memory_gate_active = previous

    def _send_operational_memory_gate_once(self, declaration: dict[str, Any]) -> None:
        sender = getattr(self, "_send_operational_memory_gate", None)
        if callable(sender):
            sender(declaration)
        else:
            self.Send(tools=[declaration], run_tools=True, mode="chat", stream=False)

    @staticmethod
    def _build_operational_memory_gate_missing_tool_feedback() -> str:
        return (
            "Error: RuntimeError: operational memory gate did not call "
            "record_operational_memory. Call record_operational_memory exactly once now. "
            "Use action=skip if no reusable operational memory should be recorded."
        )

    def _operational_memory_gate_completed(self, executions: object) -> bool:
        if not bool(getattr(self, "_operational_memory_gate_active", False)):
            return False
        for item in executions if isinstance(executions, list) else []:
            name = self._execution_tool_name(item)
            if name == "record_operational_memory":
                return True
        return False

    def _ensure_operational_memory_tool_registered(self) -> dict[str, Any]:
        from src.operational_memory_tool import record_operational_memory
        from src.operational_memory_tool import record_operational_memory_declaration

        self.tools.function_map["record_operational_memory"] = record_operational_memory
        return record_operational_memory_declaration

    def _has_operational_memory_record_since(self, start_index: int) -> bool:
        messages = getattr(self, "messages", []) or []
        for item in messages[start_index:] if isinstance(messages, list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if (
                role in {"tool", "function"}
                and str(item.get("name") or "").strip() == "record_operational_memory"
                and self._record_memory_result_ok(item.get("content"))
            ):
                return True
        return False

    def _has_operational_memory_tool_call_since(self, start_index: int) -> bool:
        messages = getattr(self, "messages", []) or []
        for item in messages[start_index:] if isinstance(messages, list) else []:
            if not isinstance(item, dict):
                continue
            role = str(item.get("role") or "").strip().lower()
            if role in {"tool", "function"} and str(item.get("name") or "").strip() == "record_operational_memory":
                return True
        return False

    @staticmethod
    def _record_memory_result_ok(content: object) -> bool:
        try:
            payload = json.loads(str(content or ""))
        except Exception:
            return False
        if not isinstance(payload, dict):
            return False
        if payload.get("ok") is True:
            return True
        return str(payload.get("status") or "").strip().lower() in {"success", "completed"}

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

    def _build_operational_memory_gate_prompt(self, failures: list[dict[str, Any]]) -> str:
        provider_name = str(getattr(self, "provider_name", "") or "").strip()
        memory_path = str(getattr(self, "current_memory_path", "") or "").strip()
        scope = {
            "provider": provider_name,
            "memory_path": memory_path,
        }
        try:
            stored_memory = operational_memory_snapshot(operational_memory_path_for_agent(self))
        except Exception as exc:
            stored_memory = json.dumps(
                {"schema_version": 1, "memories": {}, "read_error": f"{type(exc).__name__}: {exc}"},
                ensure_ascii=False,
            )
        return (
            "A tool call failed. Before using any other tools, you should call "
            "record_operational_memory exactly once. This call is required even when no memory "
            "is worth recording; use action=skip for that decision. "
            "This is a memory decision gate, not a task completion signal; if no memory is recorded, "
            "the runtime may continue the original task.\n"
            "You are given the full current operational memory below. Edit or correct it when needed. "
            "Use action=replace when you need to rewrite the memory set after reviewing existing entries. "
            "Use action=upsert only when the failure reveals a reusable operational lesson. "
            "Use action=skip for typos, transient failures, speculative failures, or errors with no long-term value. "
            "Use action=resolve when an existing operational memory is now obsolete.\n"
            "For replace, pass the corrected memories object using the same shape as current_operational_memory.memories. "
            "For upsert, provide kind, title, lesson, evidence, scope, confidence, and optional avoid/prefer lists. "
            "Store conclusions, not raw logs. Keep lessons short and scoped.\n"
            f"Suggested scope baseline: {json.dumps(scope, ensure_ascii=False)}\n"
            f"Current operational memory: {stored_memory}\n"
            f"Failed tool calls: {json.dumps(failures, ensure_ascii=False)}"
        )

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
