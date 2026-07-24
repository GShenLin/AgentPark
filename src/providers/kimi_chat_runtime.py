from __future__ import annotations

from typing import Any

from src.kimi_model_contract import build_kimi_reasoning_fields
from src.kimi_model_contract import has_kimi_web_search_tool
from src.providers.openai_chat_runtime import OpenAIChatRuntime
from src.providers.server_tool_protocol import build_server_tool_activity
from src.providers.tool_turn_protocol import prepare_chat_completions_messages


class KimiChatRuntime(OpenAIChatRuntime):
    def _build_chat_payload(
        self,
        *,
        messages: list[dict[str, Any]],
        active_tools: list[dict[str, Any]] | None,
        reasoning_effort: object,
        thinking_mode: object,
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config["model"],
            "messages": prepare_chat_completions_messages(messages),
        }
        if active_tools:
            payload["tools"] = active_tools
        payload.update(
            build_kimi_reasoning_fields(
                model=self.config.get("model"),
                thinking_mode=thinking_mode,
                reasoning_effort=reasoning_effort,
                web_search_enabled=has_kimi_web_search_tool(active_tools),
            )
        )
        if stream:
            payload["stream"] = True
        return payload

    def _assistant_tool_call_message_fields(self, message: dict[str, Any], tool_calls: list[dict]) -> dict[str, Any]:
        fields = super()._assistant_tool_call_message_fields(message, tool_calls)
        reasoning_content = message.get("reasoning_content")
        if isinstance(reasoning_content, str) and reasoning_content:
            fields["reasoning_content"] = reasoning_content
        return fields

    def _assistant_final_message_fields(self, message: dict[str, Any]) -> dict[str, Any]:
        reasoning_content = message.get("reasoning_content")
        return {"reasoning_content": reasoning_content} if isinstance(reasoning_content, str) and reasoning_content else {}

    def _attach_stream_thinking_to_message(self, message: dict[str, Any], thinking_text: str) -> None:
        if thinking_text:
            message["reasoning_content"] = thinking_text

    def _handle_chat_completions_result(self, result, **kwargs):
        self._complete_pending_kimi_web_search_calls()
        return super()._handle_chat_completions_result(result, **kwargs)

    def _complete_pending_kimi_web_search_calls(self) -> None:
        pending = getattr(self.host, "_kimi_pending_web_search_calls", None)
        if not isinstance(pending, dict) or not pending:
            return
        callback = getattr(self, "tool_event_callback", None)
        for call_id, action in list(pending.items()):
            event = build_server_tool_activity(
                {
                    "type": "web_search_call",
                    "id": call_id,
                    "status": "completed",
                    "action": action if isinstance(action, dict) else {},
                },
                status="completed",
                provider="kimi",
            )
            if event is not None and callable(callback):
                callback(event)
        pending.clear()


__all__ = ["KimiChatRuntime"]
