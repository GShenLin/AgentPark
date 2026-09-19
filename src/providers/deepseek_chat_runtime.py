from __future__ import annotations

import json
from typing import Any

from src.providers.deepseek_errors import DeepSeekRuntimeError, deepseek_transport_error
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

        max_tokens = self.config.get("maxTokens")
        if max_tokens is not None:
            if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
                raise ValueError("DeepSeek maxTokens must be a positive integer.")
            payload["max_tokens"] = max_tokens

        for item in payload["messages"]:
            if item.get("role") == "assistant" and item.get("content") is None:
                item["content"] = ""

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

    def _parse_sse_json_event(self, data_text: str, *, stage: str):
        try:
            return json.loads(data_text)
        except json.JSONDecodeError as exc:
            raise DeepSeekRuntimeError(
                f"{stage}: malformed DeepSeek SSE payload: {exc}",
                "MALFORMED_RESPONSE",
            ) from exc

    def _validate_chat_stream_completion(self, *, saw_done: bool) -> None:
        if not saw_done:
            raise DeepSeekRuntimeError(
                "DeepSeek SSE stream ended without [DONE]",
                "STREAM_CLOSED",
            )

    @staticmethod
    def _chat_terminal_error(*, endpoint: str, error: object, message: str) -> RuntimeError:
        _ = message
        return deepseek_transport_error(endpoint, error)

    def _handle_chat_completions_result(self, result, **kwargs):
        choices = result.get("choices") if isinstance(result, dict) else None
        message = (choices[0] or {}).get("message") if isinstance(choices, list) and choices else None
        if isinstance(message, dict):
            has_content = bool(str(message.get("content") or ""))
            has_reasoning = bool(str(message.get("reasoning_content") or ""))
            has_tool_calls = bool(message.get("tool_calls"))
            if not has_content and not has_reasoning and not has_tool_calls:
                raise DeepSeekRuntimeError(
                    "DeepSeek returned a completed response with no content",
                    "EMPTY_RESPONSE",
                )
        return super()._handle_chat_completions_result(result, **kwargs)
