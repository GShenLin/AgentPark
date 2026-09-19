from __future__ import annotations

import json
import math
from typing import Any

from src.session_context_compaction_tool import compact_session_context
from src.session_context_compaction_tool import compact_session_context_declaration


SESSION_CONTEXT_CHECKPOINT_PREFIX = "[Session Context Checkpoint]"
SESSION_CONTEXT_COMPACTION_PROMPT = (
    "The complete provider request is approaching its configured context limit. "
    "compact_session_context is the only function tool available for this maintenance step. "
    "Summarize the selected older session prefix into a strict continuation checkpoint. "
    "Preserve the user's objective, exact constraints, changed files or external state, confirmed facts, "
    "verification results, failed approaches, unresolved risks, and the immediate next action. "
    "Do not report task completion merely because compaction succeeded."
)


class SessionContextCompactionMixin:
    def _prepare_session_context_compaction_if_needed(
        self,
        active_tools: object,
        *,
        observed_input_tokens: object = None,
    ) -> bool:
        self._restore_session_context_checkpoint()
        if not self._session_context_compaction_enabled():
            return False
        tool_gate_active = getattr(self, "_tool_context_compaction_gate_active_now", None)
        if callable(tool_gate_active) and tool_gate_active():
            return False
        if bool(getattr(self, "_session_context_compaction_active", False)):
            return False
        if bool(getattr(self, "_session_context_compaction_skip_until_provider_request", False)):
            return False

        messages = getattr(self, "messages", None)
        if not isinstance(messages, list):
            return False
        estimated_tokens = self._non_negative_int(observed_input_tokens)
        if estimated_tokens <= 0:
            estimated_tokens = self._estimate_session_request_tokens(messages, active_tools)
        threshold_tokens = self._session_context_compaction_threshold_tokens()
        if estimated_tokens < threshold_tokens:
            return False

        indexes = self._session_context_compaction_prefix_indexes(messages)
        if len(indexes) < 2:
            return False
        prompt = self.RuntimeInstructionMessage(SESSION_CONTEXT_COMPACTION_PROMPT)
        self._session_context_compaction_active = True
        self._session_context_compaction_target_messages = messages
        self._session_context_compaction_indexes = tuple(indexes)
        self._session_context_compaction_prompt = prompt
        self._session_context_compaction_estimated_tokens = estimated_tokens
        self._session_context_compaction_changed = False
        self._session_context_compaction_failures = 0
        self._session_context_compaction_had_previous_function = (
            "compact_session_context" in self.tools.function_map
        )
        self._session_context_compaction_previous_function = self.tools.function_map.get(
            "compact_session_context"
        )
        self.tools.function_map["compact_session_context"] = compact_session_context
        messages.append(prompt)
        emitter = getattr(self, "_emit_provider_runtime_notice", None)
        if callable(emitter):
            emitter(
                message=json.dumps(
                    {
                        "estimated_input_tokens": estimated_tokens,
                        "threshold_tokens": threshold_tokens,
                        "selected_message_count": len(indexes),
                        "retain_percent": self._session_context_compaction_retain_percent(),
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                stage="session_context_compaction_triggered",
            )
        return True

    def _session_context_compaction_active_tools(self, active_tools: object) -> object:
        if not bool(getattr(self, "_session_context_compaction_active", False)):
            return active_tools
        return [compact_session_context_declaration]

    def _session_context_compaction_active_now(self) -> bool:
        return bool(getattr(self, "_session_context_compaction_active", False))

    def _apply_session_context_compaction(self, *, reason: object, summary: object) -> dict[str, Any]:
        if not self._session_context_compaction_active_now():
            raise RuntimeError("session context compaction gate is not active")
        reason_text = str(reason or "").strip()
        if not reason_text:
            raise ValueError("reason is required")
        summary_payload = self._normalize_session_context_summary(summary)
        messages = getattr(self, "_session_context_compaction_target_messages", None)
        indexes = getattr(self, "_session_context_compaction_indexes", ())
        if not isinstance(messages, list) or not isinstance(indexes, tuple):
            raise RuntimeError("session context compaction target is unavailable")
        selected = [index for index in indexes if isinstance(index, int) and 0 <= index < len(messages)]
        if len(selected) < 2:
            raise RuntimeError("session context compaction prefix is no longer stable")

        insert_at = min(selected)
        selected_ids = {id(messages[index]) for index in selected}
        messages[:] = [message for message in messages if id(message) not in selected_ids]
        checkpoint_text = self._render_session_context_checkpoint(reason_text, summary_payload)
        messages.insert(insert_at, self.RuntimeInstructionMessage(checkpoint_text))
        self._session_context_compaction_changed = True

        ledger = self._agent_step_ledger()
        if ledger is not None:
            ledger.append(
                "session_context_compacted",
                step_id=str(getattr(self, "_agentpark_current_step_id", "") or ""),
                reason=reason_text,
                summary=summary_payload,
                checkpoint=checkpoint_text,
                replaced_message_count=len(selected),
                estimated_input_tokens=int(
                    getattr(self, "_session_context_compaction_estimated_tokens", 0) or 0
                ),
            )
        return {
            "status": "completed",
            "changed": True,
            "replaced_message_count": len(selected),
        }

    def _session_context_compaction_gate_completed(self, executions: object) -> bool:
        if not self._session_context_compaction_active_now():
            return False
        matched = False
        success = False
        for execution in executions if isinstance(executions, list) else []:
            name = str(
                execution.get("func_name") if isinstance(execution, dict) else getattr(execution, "func_name", "")
                or ""
            )
            if name != "compact_session_context":
                continue
            matched = True
            status = str(
                execution.get("status") if isinstance(execution, dict) else getattr(execution, "status", "")
                or ""
            ).lower()
            success = status in {"", "ok", "success", "completed"} and bool(
                getattr(self, "_session_context_compaction_changed", False)
            )
        if not matched:
            return False
        if not success:
            failures = int(getattr(self, "_session_context_compaction_failures", 0) or 0) + 1
            self._session_context_compaction_failures = failures
            detail = next(
                (
                    str(
                        execution.get("cleaned_result")
                        if isinstance(execution, dict)
                        else getattr(execution, "cleaned_result", "")
                    )
                    for execution in executions
                    if (isinstance(execution, dict) or hasattr(execution, "cleaned_result"))
                ),
                "",
            )
            if failures >= self._session_context_compaction_max_attempts():
                raise RuntimeError(
                    f"session context compaction failed after {failures} attempts: {detail[:1000]}"
                )
            return False
        self._close_session_context_compaction_gate()
        self._session_context_compaction_skip_until_provider_request = True
        return True

    def _session_context_compaction_provider_request_checkpointed(self) -> None:
        self._session_context_compaction_skip_until_provider_request = False

    def _close_session_context_compaction_gate(self) -> None:
        messages = getattr(self, "messages", None)
        prompt = getattr(self, "_session_context_compaction_prompt", None)
        if isinstance(messages, list):
            protocol_call_ids: set[str] = set()
            for message in messages:
                if not isinstance(message, dict):
                    continue
                for call in message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []:
                    function = call.get("function") if isinstance(call, dict) else None
                    if isinstance(function, dict) and function.get("name") == "compact_session_context":
                        call_id = str(call.get("id") or "").strip()
                        if call_id:
                            protocol_call_ids.add(call_id)
            messages[:] = [
                message
                for message in messages
                if message is not prompt
                and not self._is_session_compaction_protocol_message(message, protocol_call_ids)
            ]
        if bool(getattr(self, "_session_context_compaction_had_previous_function", False)):
            self.tools.function_map["compact_session_context"] = getattr(
                self, "_session_context_compaction_previous_function", None
            )
        else:
            self.tools.function_map.pop("compact_session_context", None)
        self._session_context_compaction_active = False
        self._session_context_compaction_target_messages = None
        self._session_context_compaction_indexes = ()
        self._session_context_compaction_prompt = None
        self._session_context_compaction_had_previous_function = False
        self._session_context_compaction_previous_function = None
        self._session_context_compaction_failures = 0

    def _restore_session_context_checkpoint(self) -> None:
        if bool(getattr(self, "_session_context_checkpoint_restored", False)):
            return
        self._session_context_checkpoint_restored = True
        if not self._agent_step_ledger_enabled():
            return
        ledger = self._agent_step_ledger()
        checkpoint = ledger.latest_compaction_checkpoint() if ledger is not None else None
        checkpoint_text = str((checkpoint or {}).get("checkpoint") or "").strip()
        if not checkpoint_text:
            return
        messages = getattr(self, "messages", None)
        if not isinstance(messages, list):
            return
        if any(
            isinstance(message, dict)
            and str(message.get("content") or "").startswith(SESSION_CONTEXT_CHECKPOINT_PREFIX)
            for message in messages
        ):
            return
        insert_at = next(
            (
                index + 1
                for index, message in enumerate(messages)
                if isinstance(message, dict)
                and str(message.get("role") or "").lower() in {"system", "developer"}
            ),
            0,
        )
        messages.insert(insert_at, self.RuntimeInstructionMessage(checkpoint_text))

    def _session_context_compaction_enabled(self) -> bool:
        value = getattr(self, "config", {}).get("sessionContextCompactionEnabled", False)
        if not isinstance(value, bool):
            raise ValueError("provider.sessionContextCompactionEnabled must be a boolean")
        return value

    def _session_context_compaction_threshold_tokens(self) -> int:
        context_window = self._positive_config_int("modelContextWindowTokens")
        percent = self._percent_config_int("sessionContextCompactionThresholdPercent", default=80)
        return max(1, math.floor(context_window * percent / 100))

    def _session_context_compaction_retain_percent(self) -> int:
        return self._percent_config_int("sessionContextCompactionRetainPercent", default=16)

    def _session_context_compaction_max_attempts(self) -> int:
        value = getattr(self, "config", {}).get("sessionContextCompactionMaxAttempts", 3)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 5:
            raise ValueError("provider.sessionContextCompactionMaxAttempts must be an integer between 1 and 5")
        return value

    def _session_context_compaction_prefix_indexes(self, messages: list[dict[str, Any]]) -> list[int]:
        context_window = self._positive_config_int("modelContextWindowTokens")
        retain_budget = max(1, math.floor(context_window * self._session_context_compaction_retain_percent() / 100))
        retained_tokens = 0
        retain_from = len(messages)
        for index in range(len(messages) - 1, -1, -1):
            message = messages[index]
            if not self._session_context_compaction_conversation_message(message):
                continue
            cost = self._estimate_json_tokens(message)
            if retained_tokens and retained_tokens + cost > retain_budget:
                break
            retained_tokens += cost
            retain_from = index
        while retain_from > 0 and self._message_is_tool_result(messages[retain_from]):
            retain_from -= 1
        indexes = [
            index
            for index, message in enumerate(messages[:retain_from])
            if self._session_context_compaction_conversation_message(message)
        ]
        latest_user = max(
            (
                index
                for index, message in enumerate(messages)
                if isinstance(message, dict) and str(message.get("role") or "").lower() == "user"
            ),
            default=-1,
        )
        return [index for index in indexes if index < latest_user]

    def _estimate_session_request_tokens(self, messages: object, active_tools: object) -> int:
        return self._estimate_json_tokens(messages) + self._estimate_json_tokens(active_tools) + 64

    @staticmethod
    def _estimate_json_tokens(value: object) -> int:
        text = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
        return max(1, math.ceil(len(text.encode("utf-8")) / 4))

    @staticmethod
    def _session_context_compaction_conversation_message(message: object) -> bool:
        if not isinstance(message, dict):
            return False
        return str(message.get("role") or "").strip().lower() in {
            "user",
            "assistant",
            "tool",
            "function",
        }

    @staticmethod
    def _message_is_tool_result(message: object) -> bool:
        return isinstance(message, dict) and str(message.get("role") or "").lower() in {"tool", "function"}

    @staticmethod
    def _normalize_session_context_summary(summary: object) -> dict[str, Any]:
        if not isinstance(summary, dict):
            raise ValueError("summary must be an object")
        required = (
            "task_anchor",
            "completed_facts",
            "changed_state",
            "verification",
            "failed_attempts",
            "remaining_steps",
            "immediate_next_step",
            "critical_context",
        )
        missing = [key for key in required if key not in summary]
        if missing:
            raise ValueError(f"summary is missing required fields: {', '.join(missing)}")
        normalized: dict[str, Any] = {}
        for key in required:
            value = summary.get(key)
            if key in {"task_anchor", "immediate_next_step"}:
                normalized[key] = str(value or "").strip()
            else:
                if not isinstance(value, list):
                    raise ValueError(f"summary.{key} must be an array")
                normalized[key] = [str(item) for item in value if str(item or "").strip()]
        return normalized

    @staticmethod
    def _render_session_context_checkpoint(reason: str, summary: dict[str, Any]) -> str:
        return (
            f"{SESSION_CONTEXT_CHECKPOINT_PREFIX}\n"
            f"Reason: {reason}\n"
            + json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
        )

    @staticmethod
    def _is_session_compaction_protocol_message(message: object, call_ids: set[str]) -> bool:
        if not isinstance(message, dict):
            return False
        if str(message.get("name") or "") == "compact_session_context":
            return True
        if str(message.get("tool_call_id") or "") in call_ids:
            return True
        for call in message.get("tool_calls") if isinstance(message.get("tool_calls"), list) else []:
            function = call.get("function") if isinstance(call, dict) else None
            if isinstance(function, dict) and function.get("name") == "compact_session_context":
                return True
        return False

    def _positive_config_int(self, key: str) -> int:
        value = getattr(self, "config", {}).get(key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ValueError(f"provider.{key} must be a positive integer")
        return value

    def _percent_config_int(self, key: str, *, default: int) -> int:
        value = getattr(self, "config", {}).get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
            raise ValueError(f"provider.{key} must be an integer between 1 and 100")
        return value

    @staticmethod
    def _non_negative_int(value: object) -> int:
        if isinstance(value, bool) or value is None:
            return 0
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 0


__all__ = [
    "SESSION_CONTEXT_CHECKPOINT_PREFIX",
    "SessionContextCompactionMixin",
]
