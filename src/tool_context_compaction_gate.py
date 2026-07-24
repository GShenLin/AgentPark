from __future__ import annotations

import json
from typing import Any

from src.tool_context_compaction_actions import TOOL_CONTEXT_SUMMARY_PREFIX
from src.tool_context_compaction_actions import ToolContextCompactionActionsMixin
from src.tool_context_compaction_admission import ToolContextCompactionAdmissionMixin
from src.providers.provider_message_policy import ProviderMessagePolicy
from src.value_parsing import parse_optional_int_value
from src.tool_context_compaction_trigger import ToolContextCompactionLimits
from src.tool_context_compaction_trigger import ToolContextCompactionWindow


INTERNAL_TOOL_NAMES = {"edit_operational_memory", "compact_tool_context"}
DEFAULT_MAX_GATE_PROMPT_CHARS = 200000
DEFAULT_MAX_CANDIDATE_CONTENT_CHARS = 50000
TOOL_CONTEXT_COMPACTION_RETRY_PREFIX = "[Tool Context Compaction Retry]"


class ToolContextCompactionGateMixin(ToolContextCompactionActionsMixin, ToolContextCompactionAdmissionMixin):
    def _run_tool_context_compaction_gate_if_needed(self, executions: object) -> bool:
        if not self._tool_context_compaction_enabled():
            return False
        if bool(getattr(self, "_tool_context_compaction_gate_active", False)):
            return False

        count = self._count_regular_tool_executions(executions)
        if count <= 0:
            return False
        window = self._tool_context_compaction_window_state()
        window.add_tool_executions(count)
        limits = self._tool_context_compaction_limits()
        decision = window.evaluate(
            limits,
            self._tool_context_compaction_usage_totals(),
        )
        if not decision.reached:
            return False

        candidates = self._collect_tool_context_compaction_candidates()
        if not candidates:
            self._reset_tool_context_compaction_window()
            return False
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if callable(emitter):
            emitter(
                message=json.dumps(decision.to_payload(), ensure_ascii=False),
                stage="tool_context_compaction_triggered",
            )

        original_messages = getattr(self, "messages", [])
        if not isinstance(original_messages, list):
            return False

        prompt = self._build_tool_context_compaction_gate_prompt(candidates)
        prompt_message = self.RuntimeInstructionMessage(prompt)

        self._tool_context_compaction_gate_active = True
        self._tool_context_compaction_target_messages = original_messages
        self._tool_context_compaction_candidate_map = {
            str(item["message_id"]): int(item["index"]) for item in candidates
        }
        self._tool_context_compaction_applied = False
        self._tool_context_compaction_changed = False
        self._tool_context_compaction_gate_prompt = prompt_message
        self.messages.append(self._tool_context_compaction_gate_prompt)
        function_map = self.tools.function_map
        self._tool_context_compaction_had_previous_function = "compact_tool_context" in function_map
        self._tool_context_compaction_previous_function = function_map.get("compact_tool_context")
        self._ensure_tool_context_compaction_tool_registered()
        return True

    def _tool_context_compaction_gate_completed(self, executions: object) -> bool:
        if not bool(getattr(self, "_tool_context_compaction_gate_active", False)):
            return False
        for item in executions if isinstance(executions, list) else []:
            if (
                self._execution_tool_name(item) == "compact_tool_context"
                and self._execution_completed_successfully(item)
                and bool(getattr(self, "_tool_context_compaction_applied", False))
                and bool(getattr(self, "_tool_context_compaction_changed", False))
            ):
                self._complete_tool_context_compaction_gate()
                return True
        return False

    def _tool_context_compaction_gate_active_now(self) -> bool:
        return bool(getattr(self, "_tool_context_compaction_gate_active", False))

    def _finish_tool_context_compaction_gate_with_response(self, content: object) -> bool:
        if not self._tool_context_compaction_gate_active_now():
            return False
        if isinstance(content, str):
            has_response = bool(content.strip())
        elif isinstance(content, (dict, list, tuple, set)):
            has_response = bool(content)
        else:
            has_response = content is not None
        if not has_response:
            return False
        self._close_tool_context_compaction_gate()
        return True

    def _retry_tool_context_compaction_gate(self, reason: object = "") -> None:
        if not self._tool_context_compaction_gate_active_now():
            return
        messages = getattr(self, "messages", None)
        if not isinstance(messages, list):
            raise TypeError("agent.messages must be a list for tool context compaction retry")
        messages[:] = [
            message
            for message in messages
            if not (
                isinstance(message, dict)
                and str(message.get("content") or "").startswith(TOOL_CONTEXT_COMPACTION_RETRY_PREFIX)
            )
        ]
        detail = str(reason or "").strip()
        suffix = f" Previous attempt: {detail}" if detail else ""
        messages.append(
            self.RuntimeInstructionMessage(
                f"{TOOL_CONTEXT_COMPACTION_RETRY_PREFIX}\n"
                "The compaction checkpoint is still active. If more function-tool work is needed, call "
                "compact_tool_context and reduce the eligible tool context first. If the task is already complete, "
                "return the final answer directly; a substantive response closes this checkpoint."
                f"{suffix}"
            )
        )

    def _tool_context_compaction_active_tools(self, active_tools: object) -> object:
        if not bool(getattr(self, "_tool_context_compaction_gate_active", False)):
            return active_tools
        return [self._ensure_tool_context_compaction_tool_registered()]

    def _complete_tool_context_compaction_gate(self) -> None:
        self._close_tool_context_compaction_gate()

    def _close_tool_context_compaction_gate(self) -> None:
        prompt_message = getattr(self, "_tool_context_compaction_gate_prompt", None)
        if isinstance(prompt_message, dict):
            protocol_exchange_message_ids = self._tool_context_compaction_protocol_exchange_message_ids(
                self.messages
            )
            self.messages[:] = [
                message
                for message in self.messages
                if id(message) not in protocol_exchange_message_ids
                and message is not prompt_message
                and not self._is_tool_context_compaction_protocol_message(message)
                and not (
                    isinstance(message, dict)
                    and str(message.get("content") or "").startswith(TOOL_CONTEXT_COMPACTION_RETRY_PREFIX)
                )
            ]
        if bool(getattr(self, "_tool_context_compaction_had_previous_function", False)):
            self.tools.function_map["compact_tool_context"] = getattr(
                self,
                "_tool_context_compaction_previous_function",
                None,
            )
        else:
            self.tools.function_map.pop("compact_tool_context", None)
        self._tool_context_compaction_gate_active = False
        self._tool_context_compaction_target_messages = None
        self._tool_context_compaction_candidate_map = None
        self._tool_context_compaction_gate_prompt = None
        self._tool_context_compaction_had_previous_function = False
        self._tool_context_compaction_previous_function = None
        self._tool_context_compaction_applied = False
        self._tool_context_compaction_changed = False
        self._reset_tool_context_compaction_window()

    def _ensure_tool_context_compaction_tool_registered(self) -> dict[str, Any]:
        from src.tool_context_compaction_tool import compact_tool_context
        from src.tool_context_compaction_tool import compact_tool_context_declaration

        self.tools.function_map["compact_tool_context"] = compact_tool_context
        return compact_tool_context_declaration

    def _collect_tool_context_compaction_candidates(self) -> list[dict[str, Any]]:
        messages = getattr(self, "messages", []) or []
        if not isinstance(messages, list):
            return []
        latest_user_index = -1
        for index, message in enumerate(messages):
            if isinstance(message, dict) and str(message.get("role") or "").strip().lower() == "user":
                latest_user_index = index

        candidates: list[dict[str, Any]] = []
        for index, message in enumerate(messages):
            if index <= latest_user_index or not isinstance(message, dict):
                continue
            if not self._is_tool_context_compaction_candidate(message):
                continue
            candidates.append(self._build_tool_context_candidate(index, message))
        return candidates

    def _is_tool_context_compaction_candidate(self, message: dict[str, Any]) -> bool:
        role = str(message.get("role") or "").strip().lower()
        name = str(message.get("name") or "").strip()
        if name in INTERNAL_TOOL_NAMES:
            return False
        if role in {"tool", "function"}:
            return True
        if isinstance(message.get("tool_calls"), list) and message.get("tool_calls"):
            return not self._tool_calls_are_internal(message.get("tool_calls"))
        if isinstance(message.get("parts"), list) and self._parts_include_function_call(message.get("parts")):
            return True
        if ProviderMessagePolicy.is_instruction_message(message):
            content = str(message.get("content") or "")
            return content.startswith("Tool ") and "non-retryable result" in content
        return False

    @staticmethod
    def _tool_calls_are_internal(tool_calls: object) -> bool:
        if not isinstance(tool_calls, list) or not tool_calls:
            return False
        names: list[str] = []
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            function_item = item.get("function")
            if isinstance(function_item, dict):
                name = str(function_item.get("name") or "").strip()
                if name:
                    names.append(name)
        return bool(names) and all(name in INTERNAL_TOOL_NAMES for name in names)

    @staticmethod
    def _parts_include_function_call(parts: object) -> bool:
        if not isinstance(parts, list):
            return False
        for part in parts:
            if isinstance(part, dict) and "functionCall" in part:
                return True
        return False

    def _build_tool_context_candidate(self, index: int, message: dict[str, Any]) -> dict[str, Any]:
        content = message.get("content")
        if not isinstance(content, str):
            content = json.dumps(content, ensure_ascii=False)
        max_chars = self._tool_context_compaction_max_candidate_chars()
        truncated = len(content) > max_chars
        if truncated:
            content = content[: max(0, max_chars - 3)].rstrip() + "..."
        return {
            "message_id": f"tc_{index}",
            "index": index,
            "role": str(message.get("role") or ""),
            "name": str(message.get("name") or ""),
            "tool_call_id": str(message.get("tool_call_id") or ""),
            "tool_calls": message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else None,
            "content": content,
            "content_truncated": truncated,
        }

    def _build_tool_context_compaction_gate_prompt(self, candidates: list[dict[str, Any]]) -> str:
        _ = candidates
        return (
            "Tool calls have accumulated in the current task. This is a context maintenance checkpoint. "
            "If more function-tool work is needed, call compact_tool_context before using another function tool. "
            "If the task is already complete, return the final answer directly without calling it; a substantive "
            "response closes the checkpoint and ends the current turn.\n"
            "Review the tool-call history already present in the conversation and decide what should remain. "
            "Use the latest user request as the primary task anchor. "
            "Prefer action=replace when the raw tool-call window can be replaced by a concise but actionable summary. "
            "Use action=patch when only specific messages should be deleted or rewritten. A compaction call only "
            "completes after the eligible context is actually reduced or rewritten.\n"
            "The runtime will only modify eligible message ids. Preserve: inspected file paths, line numbers, "
            "state-changing actions, failed attempts that affect next steps, important outputs, and pending decisions. "
            "Do not preserve raw logs, duplicate search results, or large file contents after extracting the useful facts.\n"
            "The summary is a strict checkpoint object. Distinguish confirmed facts, changed state, completed "
            "verification, failed attempts, and ordered remaining steps. Set immediate_next_step to exactly one "
            "remaining_steps item. Record already-sufficient reads/searches/checks in avoid_repeating, and trust "
            "those entries after compaction unless a later state change invalidates them.\n"
            "Assistant tool-call messages and their matching tool-result messages are protocol-atomic: "
            "keep or remove the whole exchange together.\n"
            "For replace, provide summary and optional keep_message_ids for raw messages that must remain. "
            "For patch, provide delete_message_ids and/or rewrites, plus optional summary.\n"
            "The resulting summary is working memory for continuation, not a completion signal. "
            "After compaction, resume the current task using the latest user request, pending work, "
            "and verification state. Do not send a final response solely because compaction completed."
        )

    def _latest_tool_context_compaction_user_input(self) -> dict[str, Any] | None:
        messages = getattr(self, "messages", []) or []
        if not isinstance(messages, list):
            return None
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "user":
                continue
            content = message.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False)
            max_chars = self._tool_context_compaction_max_candidate_chars()
            truncated = len(content) > max_chars
            if truncated:
                content = content[: max(0, max_chars - 3)].rstrip() + "..."
            return {
                "message_id": f"user_{index}",
                "index": index,
                "content": content,
                "content_truncated": truncated,
            }
        return None

    def _existing_tool_context_summaries(self) -> list[str]:
        messages = getattr(self, "messages", []) or []
        summaries: list[str] = []
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                continue
            content = str(message.get("content") or "")
            if content.startswith(TOOL_CONTEXT_SUMMARY_PREFIX):
                summaries.append(content)
        return summaries[-5:]

    def _count_regular_tool_executions(self, executions: object) -> int:
        count = 0
        for item in executions if isinstance(executions, list) else []:
            name = self._execution_tool_name(item)
            if name and name not in INTERNAL_TOOL_NAMES:
                count += 1
        return count

    def _tool_context_compaction_limits(self) -> ToolContextCompactionLimits:
        return ToolContextCompactionLimits.from_provider_config(self.config)

    def _tool_context_compaction_window_state(self) -> ToolContextCompactionWindow:
        window = getattr(self, "_tool_context_compaction_window", None)
        if not isinstance(window, ToolContextCompactionWindow):
            window = ToolContextCompactionWindow()
            self._tool_context_compaction_window = window
        return window

    def _tool_context_compaction_usage_totals(self) -> dict[str, Any]:
        snapshot_getter = getattr(self, "_provider_request_snapshot", None)
        if not callable(snapshot_getter):
            return {}
        snapshot = snapshot_getter()
        if not isinstance(snapshot, dict):
            return {}
        totals = snapshot.get("totals")
        return totals if isinstance(totals, dict) else {}

    def _reset_tool_context_compaction_window(self) -> None:
        self._tool_context_compaction_window_state().reset(
            self._tool_context_compaction_usage_totals()
        )

    def _tool_context_compaction_enabled(self) -> bool:
        provider_config = self.config
        if "toolContextCompactionEnabled" not in provider_config:
            raise ValueError(
                "provider.toolContextCompactionEnabled is required. "
                "Set it explicitly to true or false."
            )
        value = provider_config.get("toolContextCompactionEnabled")
        if not isinstance(value, bool):
            raise ValueError("provider.toolContextCompactionEnabled must be a boolean.")
        return value

    def _tool_context_compaction_max_prompt_chars(self) -> int:
        return self._tool_context_compaction_min_chars(
            "toolContextCompactionMaxPromptChars",
            DEFAULT_MAX_GATE_PROMPT_CHARS,
        )

    def _tool_context_compaction_max_candidate_chars(self) -> int:
        return self._tool_context_compaction_min_chars(
            "toolContextCompactionMaxCandidateChars",
            DEFAULT_MAX_CANDIDATE_CONTENT_CHARS,
        )

    def _tool_context_compaction_min_chars(self, key: str, default: int) -> int:
        field_name = f"provider.{key}"
        try:
            parsed = parse_optional_int_value(field_name, self.config.get(key, default), minimum=1000)
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer greater than or equal to 1000.") from exc
        if parsed is None:
            return default
        return parsed
