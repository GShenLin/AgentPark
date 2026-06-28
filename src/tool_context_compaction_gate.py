from __future__ import annotations

import json
from typing import Any

from src.value_parsing import parse_optional_int_value


TOOL_CONTEXT_SUMMARY_PREFIX = "[Tool Context Summary]"
DEFAULT_MAX_GATE_PROMPT_CHARS = 200000
DEFAULT_MAX_CANDIDATE_CONTENT_CHARS = 50000
TOOL_CONTEXT_COMPACTION_REQUIRED_ERROR = (
    "Error: tool_context_compaction_gate requires a compact_tool_context tool call. "
    "Use the provided compact_tool_context tool to compress tool-call context before "
    "executing any other instruction. Do not answer normally or call any other tool."
)
TOOL_CONTEXT_COMPACTION_REFUSED_ERROR = (
    "Tool context compaction gate failed: the model did not call compact_tool_context "
    "after being explicitly required to do so."
)


class ToolContextCompactionGateMixin:
    def _run_tool_context_compaction_gate_if_needed(self, executions: object) -> bool:
        self._tool_context_compaction_last_changed = False
        if not bool(getattr(self, "tool_context_compaction_gate_enabled", False)):
            return False
        if not self._tool_context_compaction_enabled():
            return False
        if bool(getattr(self, "_tool_context_compaction_gate_active", False)):
            return False

        count = self._count_regular_tool_executions(executions)
        if count <= 0:
            return False
        current_count = int(getattr(self, "_tool_context_compaction_since_last", 0) or 0) + count
        self._tool_context_compaction_since_last = current_count

        threshold = self._tool_context_compaction_threshold()
        if threshold <= 0 or current_count < threshold:
            return False

        candidates = self._collect_tool_context_compaction_candidates()
        if not candidates:
            self._tool_context_compaction_since_last = 0
            return False

        original_messages = getattr(self, "messages", [])
        if not isinstance(original_messages, list):
            return False

        prompt = self._build_tool_context_compaction_gate_prompt(candidates)
        gate_messages = list(original_messages)
        gate_messages.append({"role": "system", "content": prompt})

        previous_active = bool(getattr(self, "_tool_context_compaction_gate_active", False))
        previous_target = getattr(self, "_tool_context_compaction_target_messages", None)
        previous_candidates = getattr(self, "_tool_context_compaction_candidate_map", None)
        previous_applied = bool(getattr(self, "_tool_context_compaction_applied", False))
        previous_changed = bool(getattr(self, "_tool_context_compaction_changed", False))
        previous_messages = self.messages
        had_compaction_tool = "compact_tool_context" in self.tools.function_map
        previous_compaction_tool = self.tools.function_map.get("compact_tool_context")
        declaration = self._ensure_tool_context_compaction_tool_registered()

        self._tool_context_compaction_gate_active = True
        self._tool_context_compaction_target_messages = original_messages
        self._tool_context_compaction_candidate_map = {
            str(item["message_id"]): int(item["index"]) for item in candidates
        }
        self._tool_context_compaction_applied = False
        self._tool_context_compaction_changed = False
        self.messages = gate_messages
        applied = False
        changed = False
        try:
            sender = getattr(self, "_send_tool_context_compaction_gate", None)
            for attempt in range(2):
                if callable(sender):
                    sender(declaration)
                else:
                    self.Send(tools=[declaration], run_tools=True, mode="chat", stream=False)

                applied = bool(getattr(self, "_tool_context_compaction_applied", False))
                if applied:
                    break
                if attempt == 0:
                    self.messages.append(
                        {"role": "system", "content": TOOL_CONTEXT_COMPACTION_REQUIRED_ERROR}
                    )
        finally:
            self.messages = previous_messages
            if had_compaction_tool:
                self.tools.function_map["compact_tool_context"] = previous_compaction_tool
            else:
                self.tools.function_map.pop("compact_tool_context", None)
            self._tool_context_compaction_gate_active = previous_active
            self._tool_context_compaction_target_messages = previous_target
            self._tool_context_compaction_candidate_map = previous_candidates
            applied = bool(getattr(self, "_tool_context_compaction_applied", False))
            changed = bool(getattr(self, "_tool_context_compaction_changed", False))
            self._tool_context_compaction_applied = previous_applied
            self._tool_context_compaction_changed = previous_changed

        if not applied:
            self._tool_context_compaction_since_last = 0
            self._tool_context_compaction_last_changed = False
            raise RuntimeError(TOOL_CONTEXT_COMPACTION_REFUSED_ERROR)
        self._tool_context_compaction_since_last = 0
        self._tool_context_compaction_last_changed = changed
        return True

    def _tool_context_compaction_changed_last_run(self) -> bool:
        return bool(getattr(self, "_tool_context_compaction_last_changed", False))

    def _tool_context_compaction_gate_completed(self, executions: object) -> bool:
        if not bool(getattr(self, "_tool_context_compaction_gate_active", False)):
            return False
        for item in executions if isinstance(executions, list) else []:
            if self._execution_tool_name(item) == "compact_tool_context":
                return True
        return False

    def _ensure_tool_context_compaction_tool_registered(self) -> dict[str, Any]:
        from src.tool_context_compaction_tool import compact_tool_context
        from src.tool_context_compaction_tool import compact_tool_context_declaration

        self.tools.function_map["compact_tool_context"] = compact_tool_context
        return compact_tool_context_declaration

    def _apply_tool_context_compaction(
        self,
        *,
        action: object,
        reason: object,
        summary: object,
        keep_message_ids: list,
        delete_message_ids: list,
        rewrites: list,
    ) -> dict[str, Any]:
        if not bool(getattr(self, "_tool_context_compaction_gate_active", False)):
            raise RuntimeError("compact_tool_context can only run inside the compaction gate")

        action_text = str(action or "").strip().lower()
        if action_text not in {"replace", "patch", "skip"}:
            raise ValueError("action must be one of replace, patch, or skip")
        reason_text = str(reason or "").strip()
        if not reason_text:
            raise ValueError("reason is required")

        target_messages = getattr(self, "_tool_context_compaction_target_messages", None)
        candidate_map = getattr(self, "_tool_context_compaction_candidate_map", None)
        if not isinstance(target_messages, list) or not isinstance(candidate_map, dict):
            raise RuntimeError("tool context compaction target is unavailable")

        eligible_ids = set(candidate_map.keys())
        keep_ids = self._normalize_message_id_set(keep_message_ids) & eligible_ids
        delete_ids = self._normalize_message_id_set(delete_message_ids) & eligible_ids
        normalized_rewrites = self._normalize_tool_context_rewrites(rewrites, eligible_ids)
        summary_text = self._normalize_tool_context_summary(summary)

        if action_text == "skip":
            self._tool_context_compaction_applied = True
            self._tool_context_compaction_changed = False
            return {"ok": True, "action": "skip", "reason": reason_text, "changed": False}

        if action_text == "replace" and not summary_text:
            raise ValueError("summary is required for action=replace")

        removed_ids: set[str] = set()
        rewritten_ids: set[str] = set()

        if action_text == "replace":
            remove_ids = eligible_ids - keep_ids - set(normalized_rewrites.keys())
            insert_at = self._first_candidate_index(candidate_map, remove_ids or eligible_ids)
            rewritten_ids.update(
                self._apply_message_rewrites(target_messages, candidate_map, normalized_rewrites)
            )
            self._remove_messages_by_candidate_ids(target_messages, candidate_map, remove_ids)
            removed_ids.update(remove_ids)
            if summary_text:
                self._insert_tool_context_summary(target_messages, insert_at, summary_text, reason_text)
        else:
            insert_at = self._first_candidate_index(candidate_map, delete_ids or set(normalized_rewrites.keys()))
            rewritten_ids.update(
                self._apply_message_rewrites(target_messages, candidate_map, normalized_rewrites)
            )
            self._remove_messages_by_candidate_ids(target_messages, candidate_map, delete_ids)
            removed_ids.update(delete_ids)
            if summary_text:
                self._insert_tool_context_summary(target_messages, insert_at, summary_text, reason_text)

        self._tool_context_compaction_applied = True
        self._tool_context_compaction_changed = bool(removed_ids or rewritten_ids or summary_text)
        return {
            "ok": True,
            "action": action_text,
            "reason": reason_text,
            "changed": bool(removed_ids or rewritten_ids or summary_text),
            "removed_count": len(removed_ids),
            "rewritten_count": len(rewritten_ids),
            "summary_inserted": bool(summary_text),
        }

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
        if name in {"record_operational_memory", "compact_tool_context"}:
            return False
        if role in {"tool", "function"}:
            return True
        if isinstance(message.get("tool_calls"), list) and message.get("tool_calls"):
            return not self._tool_calls_are_internal(message.get("tool_calls"))
        if isinstance(message.get("parts"), list) and self._parts_include_function_call(message.get("parts")):
            return True
        if role == "system":
            content = str(message.get("content") or "")
            return content.startswith("Tool ") and "non-retryable result" in content
        return False

    @staticmethod
    def _tool_calls_are_internal(tool_calls: object) -> bool:
        if not isinstance(tool_calls, list) or not tool_calls:
            return False
        internal_names = {"record_operational_memory", "compact_tool_context"}
        names: list[str] = []
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            function_item = item.get("function")
            if isinstance(function_item, dict):
                name = str(function_item.get("name") or "").strip()
                if name:
                    names.append(name)
        return bool(names) and all(name in internal_names for name in names)

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
        summaries = self._existing_tool_context_summaries()
        payload = {
            "existing_summaries": summaries,
            "eligible_messages": candidates,
        }
        payload_text = json.dumps(payload, ensure_ascii=False)
        max_chars = self._tool_context_compaction_max_prompt_chars()
        if len(payload_text) > max_chars:
            payload_text = payload_text[: max(0, max_chars - 3)].rstrip() + "..."
        return (
            "Tool calls have accumulated in the current task. Before using any other tools, you must call "
            "compact_tool_context exactly once. This is a context maintenance gate.\n"
            "Review the eligible tool-call messages below and decide what should remain in the model context. "
            "Prefer action=replace when the raw tool-call window can be replaced by a concise but actionable summary. "
            "Use action=patch when only specific messages should be deleted or rewritten. Use action=skip only when "
            "the raw messages are still required.\n"
            "The runtime will only modify eligible message ids. Preserve: inspected file paths, line numbers, "
            "state-changing actions, failed attempts that affect next steps, important outputs, and pending decisions. "
            "Do not preserve raw logs, duplicate search results, or large file contents after extracting the useful facts.\n"
            "For replace, provide summary and optional keep_message_ids for raw messages that must remain. "
            "For patch, provide delete_message_ids and/or rewrites, plus optional summary.\n"
            "The resulting summary is working memory for continuation, not a completion signal. "
            "After compaction, resume the current task using the latest user request, pending work, "
            "and verification state. Do not send a final response solely because compaction completed.\n"
            f"Compaction input: {payload_text}"
        )

    def _existing_tool_context_summaries(self) -> list[str]:
        messages = getattr(self, "messages", []) or []
        summaries: list[str] = []
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "system":
                continue
            content = str(message.get("content") or "")
            if content.startswith(TOOL_CONTEXT_SUMMARY_PREFIX):
                summaries.append(content)
        return summaries[-5:]

    def _count_regular_tool_executions(self, executions: object) -> int:
        count = 0
        for item in executions if isinstance(executions, list) else []:
            name = self._execution_tool_name(item)
            if name and name not in {"record_operational_memory", "compact_tool_context"}:
                count += 1
        return count

    def _tool_context_compaction_threshold(self) -> int:
        provider_config = self.config
        if "toolContextCompactionEveryToolCalls" not in provider_config:
            raise ValueError(
                "provider.toolContextCompactionEveryToolCalls is required when "
                "provider.toolContextCompactionEnabled is true."
            )
        field_name = "provider.toolContextCompactionEveryToolCalls"
        try:
            parsed = parse_optional_int_value(
                field_name,
                provider_config.get("toolContextCompactionEveryToolCalls"),
                minimum=0,
            )
        except ValueError as exc:
            raise ValueError(f"{field_name} must be an integer greater than or equal to zero.") from exc
        if parsed is None:
            raise ValueError(f"{field_name} must be an integer greater than or equal to zero.")
        return parsed

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

    @staticmethod
    def _normalize_message_id_set(values: list) -> set[str]:
        return {str(item or "").strip() for item in values if str(item or "").strip()}

    @staticmethod
    def _normalize_tool_context_summary(summary: object) -> str:
        if isinstance(summary, str):
            return summary.strip()
        if summary in {None, ""}:
            return ""
        return json.dumps(summary, ensure_ascii=False)

    @staticmethod
    def _normalize_tool_context_rewrites(rewrites: list, eligible_ids: set[str]) -> dict[str, str]:
        normalized: dict[str, str] = {}
        for item in rewrites:
            if not isinstance(item, dict):
                continue
            message_id = str(item.get("message_id") or "").strip()
            if message_id not in eligible_ids:
                continue
            normalized[message_id] = str(item.get("content") or "")
        return normalized

    @staticmethod
    def _first_candidate_index(candidate_map: dict[str, int], message_ids: set[str]) -> int:
        indexes = [candidate_map[item] for item in message_ids if item in candidate_map]
        return min(indexes) if indexes else len(candidate_map)

    @staticmethod
    def _remove_messages_by_candidate_ids(
        messages: list[dict[str, Any]],
        candidate_map: dict[str, int],
        message_ids: set[str],
    ) -> None:
        indexes = sorted((candidate_map[item] for item in message_ids if item in candidate_map), reverse=True)
        for index in indexes:
            if 0 <= index < len(messages):
                messages.pop(index)

    @staticmethod
    def _apply_message_rewrites(
        messages: list[dict[str, Any]],
        candidate_map: dict[str, int],
        rewrites: dict[str, str],
    ) -> set[str]:
        rewritten: set[str] = set()
        for message_id, content in rewrites.items():
            index = candidate_map.get(message_id)
            if not isinstance(index, int) or index < 0 or index >= len(messages):
                continue
            message = messages[index]
            if not isinstance(message, dict):
                continue
            role = str(message.get("role") or "").strip().lower()
            if role not in {"tool", "function", "system"}:
                continue
            message["content"] = content
            rewritten.add(message_id)
        return rewritten

    @staticmethod
    def _insert_tool_context_summary(
        messages: list[dict[str, Any]],
        index: int,
        summary: str,
        reason: str,
    ) -> None:
        summary_message = {
            "role": "system",
            "content": f"{TOOL_CONTEXT_SUMMARY_PREFIX}\nReason: {reason}\n{summary}",
        }
        insert_at = max(0, min(index, len(messages)))
        messages.insert(insert_at, summary_message)
