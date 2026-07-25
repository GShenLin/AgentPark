from __future__ import annotations

# Maps Claude Agent SDK messages into AgentPark live events.
import json
import time
from collections.abc import Callable
from typing import Any

from claude_agent_sdk import AssistantMessage
from claude_agent_sdk import ResultMessage
from claude_agent_sdk import StreamEvent
from claude_agent_sdk import TextBlock
from claude_agent_sdk import ThinkingBlock
from claude_agent_sdk import ToolResultBlock
from claude_agent_sdk import ToolUseBlock
from claude_agent_sdk import UserMessage

from src.node_stream_protocol import build_node_message_delta
from src.node_stream_protocol import build_node_message_done
from src.node_stream_protocol import build_node_thinking_delta
from src.providers.provider_runtime_events import PROVIDER_REQUEST_COMPLETED_STAGE
from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE


StreamCallback = Callable[[dict[str, Any]], None]


class ClaudeLiveBridge:
    """Projects Claude Agent SDK messages onto AgentPark's live event protocol."""

    def __init__(
        self,
        stream_callback: StreamCallback | None,
        *,
        tool_event_callback: StreamCallback | None = None,
        provider_id: str = "claude",
    ) -> None:
        self.stream_callback = stream_callback if callable(stream_callback) else None
        self.tool_event_callback = tool_event_callback if callable(tool_event_callback) else None
        self.provider_id = str(provider_id or "").strip() or "claude"
        self.text = ""
        self.thinking_text = ""
        self.provider_requests: list[dict[str, Any]] = []
        self.provider_gateway_requests: list[dict[str, Any]] = []
        self.runtime_tool_calls: dict[str, dict[str, Any]] = {}
        self.session_id = ""
        self._provider_request_index = 0
        self._tool_started_at: dict[str, float] = {}
        self._tool_names: dict[str, str] = {}
        self._tool_arguments: dict[str, dict[str, Any]] = {}
        self._partial_tool_json: dict[int, str] = {}
        self._partial_tool_ids: dict[int, str] = {}
        self._saw_text_delta = False
        self._saw_thinking_delta = False

    def handle(self, message: object) -> None:
        if isinstance(message, StreamEvent):
            self._stream_event(message)
        elif isinstance(message, AssistantMessage):
            self._assistant_message(message)
        elif isinstance(message, UserMessage):
            self._user_message(message)
        elif isinstance(message, ResultMessage):
            self._result_message(message)

    def observe_gateway_request(self, payload: dict[str, Any]) -> None:
        observation = dict(payload)
        self.provider_gateway_requests.append(observation)
        self._emit(
            {
                "type": "runtime_notice",
                "source": "claude_provider_gateway",
                "stage": "provider_gateway_request",
                "provider": self.provider_id,
                "message": json.dumps(observation, ensure_ascii=False, sort_keys=True),
            }
        )

    def emit_done(self, final_text: object) -> dict[str, Any]:
        text = str(final_text or "")
        if text and text != self.text:
            starts_with_stream = text.startswith(self.text)
            delta = text[len(self.text) :] if starts_with_stream else text
            self.text = text
            self._emit(build_node_message_delta(delta, text, force=not starts_with_stream))
        structured = self.structured_result(text)
        self._emit(
            build_node_message_done(
                text,
                response_metadata=structured.get("response_metadata"),
            )
        )
        return structured

    def structured_result(self, final_text: object | None = None) -> dict[str, Any]:
        text = self.text if final_text is None else str(final_text or "")
        metadata: dict[str, Any] = {}
        if self.session_id:
            metadata["claude_session_id"] = self.session_id
        if self.runtime_tool_calls:
            metadata["runtime_tool_calls"] = list(self.runtime_tool_calls.values())
        if self.provider_requests:
            metadata["provider_requests"] = list(self.provider_requests)
        if self.provider_gateway_requests:
            metadata["provider_gateway_requests"] = list(self.provider_gateway_requests)
        result: dict[str, Any] = {"response": text}
        if metadata:
            result["response_metadata"] = metadata
        return result

    def _stream_event(self, message: StreamEvent) -> None:
        if message.session_id:
            self.session_id = message.session_id
        event = message.event
        if not isinstance(event, dict):
            raise ValueError("Claude stream event payload must be an object.")
        event_type = str(event.get("type") or "")
        if event_type == "content_block_start":
            block = event.get("content_block")
            if not isinstance(block, dict) or str(block.get("type") or "") != "tool_use":
                return
            index = _nonnegative_int(event.get("index"), "content block index")
            call_id = _required_text(block.get("id"), "Claude tool_use id")
            name = _required_text(block.get("name"), "Claude tool_use name")
            self._partial_tool_ids[index] = call_id
            self._partial_tool_json[index] = ""
            self._tool_start(call_id, name, {})
            return
        if event_type != "content_block_delta":
            return
        delta = event.get("delta")
        if not isinstance(delta, dict):
            raise ValueError("Claude content_block_delta requires a delta object.")
        delta_type = str(delta.get("type") or "")
        if delta_type == "text_delta":
            self._saw_text_delta = True
            self._message_delta(str(delta.get("text") or ""))
        elif delta_type == "thinking_delta":
            self._saw_thinking_delta = True
            self._thinking_delta(str(delta.get("thinking") or ""))
        elif delta_type == "input_json_delta":
            index = _nonnegative_int(event.get("index"), "content block index")
            if index not in self._partial_tool_ids:
                raise ValueError("Claude input_json_delta has no preceding tool_use block.")
            self._partial_tool_json[index] += str(delta.get("partial_json") or "")

    def _assistant_message(self, message: AssistantMessage) -> None:
        if message.session_id:
            self.session_id = message.session_id
        for block in message.content:
            if isinstance(block, TextBlock):
                if not self._saw_text_delta:
                    self._message_delta(block.text)
            elif isinstance(block, ThinkingBlock):
                if not self._saw_thinking_delta:
                    self._thinking_delta(block.thinking)
            elif isinstance(block, ToolUseBlock):
                arguments = dict(block.input)
                self._tool_arguments[block.id] = arguments
                self._tool_start(block.id, block.name, arguments)
        self._saw_text_delta = False
        self._saw_thinking_delta = False
        self._provider_request_completed(message.usage, message.message_id, message.model)

    def _user_message(self, message: UserMessage) -> None:
        content = message.content
        blocks = content if isinstance(content, list) else []
        for block in blocks:
            if isinstance(block, ToolResultBlock):
                self._tool_end(
                    block.tool_use_id,
                    content=block.content,
                    is_error=bool(block.is_error),
                )

    def _result_message(self, message: ResultMessage) -> None:
        self.session_id = str(message.session_id or self.session_id)
        if message.is_error:
            details = list(message.errors or [])
            if message.result:
                details.append(message.result)
            self._emit(
                {
                    "type": "runtime_notice",
                    "source": "claude_agent_sdk",
                    "stage": "result_error",
                    "provider": self.provider_id,
                    "message": "\n".join(details) or message.subtype,
                }
            )

    def _message_delta(self, delta: str) -> None:
        if not delta:
            return
        self.text += delta
        self._emit(build_node_message_delta(delta, self.text))

    def _thinking_delta(self, delta: str) -> None:
        if not delta:
            return
        self.thinking_text += delta
        self._emit(build_node_thinking_delta(delta, self.thinking_text, provider="claude"))

    def _tool_start(self, call_id: str, name: str, arguments: dict[str, Any]) -> None:
        if call_id in self._tool_started_at:
            if arguments:
                self._tool_arguments[call_id] = dict(arguments)
            return
        self._tool_started_at[call_id] = time.monotonic()
        self._tool_names[call_id] = name
        self._tool_arguments[call_id] = dict(arguments)
        event = {
            "type": "tool_call_start",
            "name": name,
            "call_id": call_id,
            "provider": "claude",
            "arguments": dict(arguments),
            "status": "running",
        }
        self._remember_tool_event(event)
        self._emit_tool(event)

    def _tool_end(self, call_id: str, *, content: object, is_error: bool) -> None:
        normalized_id = _required_text(call_id, "Claude tool result id")
        if normalized_id not in self._tool_started_at:
            self._tool_start(
                normalized_id,
                self._tool_names.get(normalized_id, "unknown_tool"),
                self._tool_arguments.get(normalized_id, {}),
            )
        started_at = self._tool_started_at.pop(normalized_id)
        preview = _result_preview(content)
        event: dict[str, Any] = {
            "type": "tool_call_end",
            "name": self._tool_names.get(normalized_id, "unknown_tool"),
            "call_id": normalized_id,
            "provider": "claude",
            "arguments": dict(self._tool_arguments.get(normalized_id, {})),
            "status": "failed" if is_error else "completed",
            "duration_ms": int(round(max(0.0, (time.monotonic() - started_at) * 1000.0))),
            "result_preview": preview[:4000],
            "result_chars": len(preview),
            "result_preview_truncated": len(preview) > 4000,
        }
        if is_error:
            event["error"] = preview or "Claude tool execution failed."
        self._remember_tool_event(event)
        self._emit_tool(event)

    def _provider_request_completed(
        self,
        usage: object,
        response_id: object,
        model: object,
    ) -> None:
        self._provider_request_index += 1
        request_index = self._provider_request_index
        summary = {
            "request_index": request_index,
            "request_api": "claude_messages",
            "requested_responses_mode": "claude_agent_sdk",
            "stream": True,
            "model": str(model or ""),
        }
        normalized_id = str(response_id or "").strip()
        if normalized_id:
            summary["response_id"] = normalized_id
        self._provider_notice(PROVIDER_REQUEST_SUMMARY_STAGE, summary)
        completion = dict(summary)
        normalized_usage = _provider_usage(usage)
        if normalized_usage:
            completion["usage"] = normalized_usage
        self.provider_requests.append(completion)
        self._provider_notice(PROVIDER_REQUEST_COMPLETED_STAGE, completion)

    def _provider_notice(self, stage: str, payload: dict[str, Any]) -> None:
        self._emit(
            {
                "type": "runtime_notice",
                "source": "claude_agent_sdk",
                "stage": stage,
                "provider": self.provider_id,
                "message": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            }
        )

    def _remember_tool_event(self, event: dict[str, Any]) -> None:
        call_id = str(event.get("call_id") or "")
        current = dict(self.runtime_tool_calls.get(call_id) or {})
        current.update({key: value for key, value in event.items() if key != "type"})
        self.runtime_tool_calls[call_id] = current

    def _emit_tool(self, event: dict[str, Any]) -> None:
        if callable(self.tool_event_callback):
            self.tool_event_callback(dict(event))
        self._emit(event)

    def _emit(self, payload: dict[str, Any]) -> None:
        if callable(self.stream_callback):
            self.stream_callback(dict(payload))


def _result_preview(content: object) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json.dumps(content, ensure_ascii=False, separators=(",", ":"))


def _provider_usage(raw: object) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    fields = {
        "input_tokens": "input_tokens",
        "output_tokens": "output_tokens",
        "cache_read_input_tokens": "cache_read_input_tokens",
        "cache_creation_input_tokens": "cache_creation_input_tokens",
    }
    usage: dict[str, int] = {}
    for normalized, source in fields.items():
        value = raw.get(source)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            usage[normalized] = value
    return usage


def _required_text(raw: object, owner: str) -> str:
    value = str(raw or "").strip()
    if not value:
        raise ValueError(f"{owner} is required.")
    return value


def _nonnegative_int(raw: object, owner: str) -> int:
    if not isinstance(raw, int) or isinstance(raw, bool) or raw < 0:
        raise ValueError(f"{owner} must be a non-negative integer.")
    return raw


__all__ = ["ClaudeLiveBridge"]
