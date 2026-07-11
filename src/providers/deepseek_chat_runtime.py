from __future__ import annotations

from typing import Any

from src.providers.openai_chat_runtime import OpenAIChatRuntime


DEEPSEEK_THINKING_MODES = frozenset({"enabled", "disabled"})
DEEPSEEK_REASONING_EFFORTS = frozenset({"high", "max"})


class DeepSeekChatRuntime(OpenAIChatRuntime):
    def _build_chat_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        active_tools: list[dict[str, Any]] | None,
        reasoning_effort: object,
        thinking_mode: object,
        stream: bool,
    ) -> dict[str, Any]:
        thinking_type = str(thinking_mode or "").strip()
        if thinking_type not in DEEPSEEK_THINKING_MODES:
            allowed = ", ".join(sorted(DEEPSEEK_THINKING_MODES))
            raise ValueError(f"DeepSeek thinking must be one of: {allowed}")

        payload = super()._build_chat_payload(
            messages=messages,
            active_tools=active_tools,
            reasoning_effort=None,
            thinking_mode=None,
            stream=stream,
        )
        payload["thinking"] = {"type": thinking_type}

        effort = str(reasoning_effort or "").strip()
        if thinking_type == "enabled" and effort:
            if effort not in DEEPSEEK_REASONING_EFFORTS:
                allowed = ", ".join(sorted(DEEPSEEK_REASONING_EFFORTS))
                raise ValueError(f"DeepSeek reasoning_effort must be one of: {allowed}")
            payload["reasoning_effort"] = effort
        return payload

    def _assistant_tool_call_message_fields(self, message: dict[str, Any], tool_calls: list[dict]) -> dict[str, Any]:
        fields = super()._assistant_tool_call_message_fields(message, tool_calls)
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            fields["reasoning_content"] = reasoning_content
        return fields

    def _attach_stream_thinking_to_message(self, message: dict[str, Any], thinking_text: str) -> None:
        if thinking_text:
            message["reasoning_content"] = thinking_text
