from __future__ import annotations

from typing import Any

from src.providers.provider_message_policy import ProviderMessagePolicy
from src.tool_context_checkpoint import render_tool_context_checkpoint


TOOL_CONTEXT_SUMMARY_PREFIX = "[Tool Context Summary]"


class ToolContextCompactionActionsMixin:
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
        if action_text not in {"replace", "patch"}:
            raise ValueError("action must be one of replace or patch")
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

        if action_text == "replace" and not summary_text:
            raise ValueError("summary is required for action=replace")

        removed_ids: set[str] = set()
        rewritten_ids: set[str] = set()

        if action_text == "replace":
            keep_ids = self._expand_tool_exchange_message_ids(
                target_messages,
                candidate_map,
                keep_ids | set(normalized_rewrites.keys()),
            )
            remove_ids = eligible_ids - keep_ids - set(normalized_rewrites.keys())
            if not remove_ids and not normalized_rewrites:
                raise ValueError("compaction must remove or rewrite at least one eligible message")
            insert_at = self._first_candidate_index(candidate_map, remove_ids or eligible_ids)
            rewritten_ids.update(
                self._apply_message_rewrites(target_messages, candidate_map, normalized_rewrites)
            )
            self._remove_messages_by_candidate_ids(target_messages, candidate_map, remove_ids)
            removed_ids.update(remove_ids)
            if summary_text:
                self._insert_tool_context_summary(target_messages, insert_at, summary_text, reason_text)
        else:
            delete_ids = self._expand_tool_exchange_message_ids(target_messages, candidate_map, delete_ids)
            normalized_rewrites = {
                message_id: content
                for message_id, content in normalized_rewrites.items()
                if message_id not in delete_ids
            }
            if not delete_ids and not normalized_rewrites:
                raise ValueError("compaction must delete or rewrite at least one eligible message")
            insert_at = self._first_candidate_index(candidate_map, delete_ids or set(normalized_rewrites.keys()))
            rewritten_ids.update(
                self._apply_message_rewrites(target_messages, candidate_map, normalized_rewrites)
            )
            self._remove_messages_by_candidate_ids(target_messages, candidate_map, delete_ids)
            removed_ids.update(delete_ids)
            if summary_text:
                self._insert_tool_context_summary(target_messages, insert_at, summary_text, reason_text)

        self._tool_context_compaction_applied = True
        self._tool_context_compaction_changed = bool(removed_ids or rewritten_ids)
        return {
            "ok": True,
            "action": action_text,
            "reason": reason_text,
            "changed": bool(removed_ids or rewritten_ids),
            "removed_count": len(removed_ids),
            "rewritten_count": len(rewritten_ids),
            "summary_inserted": bool(summary_text),
        }

    @staticmethod
    def _normalize_message_id_set(values: list) -> set[str]:
        return {str(item or "").strip() for item in values if str(item or "").strip()}

    @staticmethod
    def _normalize_tool_context_summary(summary: object) -> str:
        return render_tool_context_checkpoint(summary)

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

    def _expand_tool_exchange_message_ids(
        self,
        messages: list[dict[str, Any]],
        candidate_map: dict[str, int],
        message_ids: set[str],
    ) -> set[str]:
        expanded = set(message_ids)
        if not expanded:
            return expanded
        for group in self._tool_exchange_candidate_groups(messages, candidate_map):
            if expanded.intersection(group):
                expanded.update(group)
        return expanded

    def _tool_exchange_candidate_groups(
        self,
        messages: list[dict[str, Any]],
        candidate_map: dict[str, int],
    ) -> list[set[str]]:
        groups: list[set[str]] = []
        for assistant_id, assistant_index in candidate_map.items():
            if not isinstance(assistant_index, int) or assistant_index < 0 or assistant_index >= len(messages):
                continue
            assistant = messages[assistant_index]
            if not isinstance(assistant, dict):
                continue
            if str(assistant.get("role") or "").strip().lower() != "assistant":
                continue
            call_ids = self._message_tool_call_ids(assistant)
            if not call_ids:
                continue
            group = {assistant_id}
            for candidate_id, candidate_index in candidate_map.items():
                if candidate_id == assistant_id:
                    continue
                if not isinstance(candidate_index, int) or candidate_index < 0 or candidate_index >= len(messages):
                    continue
                message = messages[candidate_index]
                if not isinstance(message, dict):
                    continue
                role = str(message.get("role") or "").strip().lower()
                if role not in {"tool", "function"}:
                    continue
                tool_call_id = str(message.get("tool_call_id") or message.get("call_id") or "").strip()
                if tool_call_id in call_ids:
                    group.add(candidate_id)
            groups.append(group)
        return groups

    @staticmethod
    def _message_tool_call_ids(message: dict[str, Any]) -> set[str]:
        ids: set[str] = set()
        tool_calls = message.get("tool_calls")
        if not isinstance(tool_calls, list):
            return ids
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            call_id = str(item.get("id") or "").strip()
            if call_id:
                ids.add(call_id)
        return ids

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
            if role not in {"tool", "function"} and not ProviderMessagePolicy.is_instruction_message(message):
                continue
            message["content"] = content
            rewritten.add(message_id)
        return rewritten

    @staticmethod
    def _execution_completed_successfully(execution: object) -> bool:
        if isinstance(execution, dict):
            status = str(execution.get("status") or "completed").strip().lower()
            error = execution.get("error")
        else:
            status = str(getattr(execution, "status", "completed") or "completed").strip().lower()
            error = getattr(execution, "error", None)
        return status in {"", "ok", "done", "success", "completed"} and not error

    @staticmethod
    def _is_tool_context_compaction_protocol_message(message: object) -> bool:
        if not isinstance(message, dict):
            return False
        if str(message.get("name") or "").strip() == "compact_tool_context":
            return True
        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for item in tool_calls:
                function_item = item.get("function") if isinstance(item, dict) else None
                if (
                    isinstance(function_item, dict)
                    and str(function_item.get("name") or "").strip() == "compact_tool_context"
                ):
                    return True
        parts = message.get("parts")
        if isinstance(parts, list):
            for part in parts:
                function_call = part.get("functionCall") if isinstance(part, dict) else None
                if (
                    isinstance(function_call, dict)
                    and str(function_call.get("name") or "").strip() == "compact_tool_context"
                ):
                    return True
        return False

    def _tool_context_compaction_protocol_exchange_message_ids(
        self,
        messages: object,
    ) -> set[int]:
        if not isinstance(messages, list):
            return set()
        selected: set[int] = set()
        for index, message in enumerate(messages):
            if not isinstance(message, dict):
                continue
            if str(message.get("role") or "").strip().lower() != "assistant":
                continue
            if not self._is_tool_context_compaction_protocol_message(message):
                continue
            selected.add(id(message))
            for following in messages[index + 1 :]:
                if not isinstance(following, dict):
                    break
                role = str(following.get("role") or "").strip().lower()
                if role not in {"tool", "function"}:
                    break
                selected.add(id(following))
        return selected

    def _insert_tool_context_summary(
        self,
        messages: list[dict[str, Any]],
        index: int,
        summary: str,
        reason: str,
    ) -> None:
        summary_message = self.RuntimeInstructionMessage(
            f"{TOOL_CONTEXT_SUMMARY_PREFIX}\nReason: {reason}\n{summary}"
        )
        insert_at = max(0, min(index, len(messages)))
        messages.insert(insert_at, summary_message)
