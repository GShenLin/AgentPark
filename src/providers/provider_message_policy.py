from __future__ import annotations

from dataclasses import dataclass
from typing import Any


RUNTIME_INSTRUCTION_KIND = "runtime_instruction"
MESSAGE_KIND_FIELD = "_agentpark_message_kind"


@dataclass(frozen=True)
class ProviderMessagePolicy:
    """Resolve AgentPark message semantics into provider protocol roles."""

    instruction_role: str

    @classmethod
    def from_config(cls, config: object) -> "ProviderMessagePolicy":
        provider_config = config if isinstance(config, dict) else {}
        responses_api = provider_config.get("responsesApi", False)
        if not isinstance(responses_api, bool):
            raise ValueError("provider.responsesApi must be a boolean.")
        return cls(instruction_role="developer" if responses_api else "system")

    def runtime_instruction_message(self, content: Any, **kwargs: Any) -> dict[str, Any]:
        reserved_fields = {"role", "content", MESSAGE_KIND_FIELD}.intersection(kwargs)
        if reserved_fields:
            fields = ", ".join(sorted(reserved_fields))
            raise ValueError(f"runtime instruction fields are policy-owned and cannot be overridden: {fields}")
        message = {
            "role": self.instruction_role,
            "content": content,
            MESSAGE_KIND_FIELD: RUNTIME_INSTRUCTION_KIND,
        }
        message.update(kwargs)
        return message

    def normalize_messages(self, messages: object) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        for message in messages if isinstance(messages, list) else []:
            if not isinstance(message, dict):
                continue
            item = dict(message)
            message_kind = str(item.pop(MESSAGE_KIND_FIELD, "") or "").strip().lower()
            role = str(item.get("role") or "").strip().lower()
            if message_kind == RUNTIME_INSTRUCTION_KIND:
                item["role"] = self.instruction_role
            elif self.instruction_role == "developer" and role == "system":
                # Responses-compatible providers express instruction messages
                # with the developer role and reject system input items.
                item["role"] = self.instruction_role
            normalized.append(item)
        return normalized

    @staticmethod
    def is_instruction_message(message: object) -> bool:
        if not isinstance(message, dict):
            return False
        message_kind = str(message.get(MESSAGE_KIND_FIELD) or "").strip().lower()
        if message_kind == RUNTIME_INSTRUCTION_KIND:
            return True
        return str(message.get("role") or "").strip().lower() in {"system", "developer"}


class ProviderMessagePolicyMixin:
    """Agent-side API for provider-neutral runtime instruction messages."""

    def RuntimeInstructionMessage(self, content: Any, **kwargs: Any) -> dict[str, Any]:
        return self._provider_message_policy().runtime_instruction_message(content, **kwargs)

    def RuntimeInstruction(self, content: Any, persist: bool = True, **kwargs: Any) -> dict[str, Any]:
        message = self.RuntimeInstructionMessage(content, **kwargs)
        self.messages.append(message)
        if persist and self.internal_memory_enabled:
            self.memory.on_message(message)
        return message

    def _provider_message_policy(self) -> ProviderMessagePolicy:
        return ProviderMessagePolicy.from_config(self.config)

    def _normalize_provider_messages(self, messages: object) -> list[dict[str, Any]]:
        return self._provider_message_policy().normalize_messages(messages)

    def _ensure_runtime_instruction(self, messages: object, content: object) -> list[dict[str, Any]]:
        text = str(content or "").strip()
        current = list(messages) if isinstance(messages, list) else []
        if not text:
            return current
        policy = self._provider_message_policy()
        for message in current:
            if not policy.is_instruction_message(message):
                continue
            if str(message.get("content") or "").strip() == text:
                return current
        instruction = self.RuntimeInstructionMessage(text)
        return self._normalize_provider_messages([instruction, *current])

    def _get_messages_with_memory(self) -> list[dict[str, Any]]:
        current_messages = [
            message
            for message in self.memory.build_messages_with_memory(self.messages)
            if str(message.get("role") or "").strip().lower() != "assistant_progress"
            and str(message.get("context_policy") or "").strip().lower() != "exclude"
        ]
        if not self.internal_memory_enabled:
            return self._normalize_provider_messages(current_messages)

        policy = self._provider_message_policy()
        instruction_messages = []
        last_user_index = -1
        for index, message in enumerate(current_messages):
            if policy.is_instruction_message(message):
                instruction_messages.append(message)
            if message.get("role") == "user":
                last_user_index = index

        if last_user_index == -1:
            non_instruction = [
                message
                for message in current_messages
                if not policy.is_instruction_message(message)
            ]
            return self._normalize_provider_messages(instruction_messages + non_instruction)

        tail = [
            message
            for message in current_messages[last_user_index:]
            if not policy.is_instruction_message(message)
        ]
        return self._normalize_provider_messages(instruction_messages + tail)
