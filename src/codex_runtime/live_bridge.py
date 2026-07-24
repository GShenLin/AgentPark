from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

from src.node_stream_protocol import build_node_message_delta
from src.node_stream_protocol import build_node_message_done
from src.node_stream_protocol import build_node_thinking_delta
from src.providers.provider_runtime_events import PROVIDER_REQUEST_COMPLETED_STAGE
from src.providers.provider_runtime_events import PROVIDER_REQUEST_SUMMARY_STAGE
from .live_bridge_tools import TOOL_ITEM_TYPES
from .live_bridge_tools import tool_arguments
from .live_bridge_tools import tool_error
from .live_bridge_tools import tool_name
from .live_bridge_tools import tool_result_preview
from .live_bridge_tools import tool_status


StreamCallback = Callable[[dict], None]


class CodexLiveBridge:
    """Projects Codex app-server notifications onto AgentPark's existing live protocol."""

    def __init__(
        self,
        stream_callback: StreamCallback | None,
        *,
        tool_event_callback: StreamCallback | None = None,
        provider_id: str = "codex",
    ) -> None:
        self.stream_callback = stream_callback if callable(stream_callback) else None
        self.tool_event_callback = tool_event_callback if callable(tool_event_callback) else None
        self.provider_id = str(provider_id or "").strip() or "codex"
        self.text = ""
        self.thinking_text = ""
        self._reasoning_items: dict[str, str] = {}
        self._tool_outputs: dict[str, str] = {}
        self._tool_started_at: dict[str, float] = {}
        self._provider_request_index = 0
        self._saw_raw_provider_response = False
        self._raw_tool_calls: dict[str, dict[str, Any]] = {}
        self.provider_requests: list[dict[str, Any]] = []
        self.provider_gateway_requests: list[dict[str, Any]] = []
        self.runtime_tool_calls: dict[str, dict[str, Any]] = {}

    def handle(self, event: dict[str, Any]) -> None:
        if not isinstance(event, dict):
            raise ValueError("Codex app-server notification must be an object.")
        method = str(event.get("method") or "").strip()
        params = event.get("params")
        params = params if isinstance(params, dict) else {}

        if method == "item/agentMessage/delta":
            self._message_delta(str(params.get("delta") or ""))
            return
        if method in {"item/reasoning/summaryTextDelta", "item/reasoning/textDelta"}:
            self._thinking_delta(
                str(params.get("itemId") or "reasoning"),
                str(params.get("delta") or ""),
            )
            return
        if method == "item/commandExecution/outputDelta":
            item_id = str(params.get("itemId") or "").strip()
            if item_id:
                self._tool_outputs[item_id] = self._tool_outputs.get(item_id, "") + str(params.get("delta") or "")
            return
        if method in {"item/started", "item/completed"}:
            item = params.get("item")
            if isinstance(item, dict):
                self._item_event(item, completed=method == "item/completed")
            return
        if method == "rawResponseItem/completed":
            item = params.get("item")
            if isinstance(item, dict):
                self._raw_response_item_completed(item)
            return
        if method == "rawResponse/completed":
            self._saw_raw_provider_response = True
            self._provider_request_completed(
                usage=params.get("usage"),
                response_id=params.get("responseId"),
                responses_mode="codex_raw_response",
            )
            return
        if method == "thread/tokenUsage/updated":
            if not self._saw_raw_provider_response:
                token_usage = params.get("tokenUsage")
                last_usage = token_usage.get("last") if isinstance(token_usage, dict) else None
                self._provider_request_completed(
                    usage=last_usage,
                    responses_mode="codex_token_usage",
                )
            return
        if method == "agentpark/providerGateway/request":
            self._provider_gateway_request(params)
            return
        if method in {"warning", "configWarning", "agentpark/serverRequestDeclined"}:
            self._runtime_notice(method, params)

    def _raw_response_item_completed(self, item: dict[str, Any]) -> None:
        item_type = str(item.get("type") or "").strip()
        call_id = str(item.get("call_id") or "").strip()
        if not call_id:
            return
        if item_type == "custom_tool_call":
            tool_item = {
                "type": "dynamicToolCall",
                "id": call_id,
                "tool": str(item.get("name") or "custom_tool").strip() or "custom_tool",
                "arguments": {"input": str(item.get("input") or "")},
                "status": "inProgress",
            }
            self._raw_tool_calls[call_id] = tool_item
            self._tool_start(tool_item)
            return
        if item_type != "custom_tool_call_output":
            return
        tool_item = dict(self._raw_tool_calls.pop(call_id, {}))
        if not tool_item:
            tool_item = {
                "type": "dynamicToolCall",
                "id": call_id,
                "tool": "custom_tool",
                "arguments": {},
            }
        tool_item["status"] = "completed"
        tool_item["contentItems"] = item.get("output")
        self._tool_end(tool_item)

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

    def _item_event(self, item: dict[str, Any], *, completed: bool) -> None:
        item_type = str(item.get("type") or "").strip()
        if item_type == "agentMessage" and completed:
            authoritative = str(item.get("text") or "")
            if authoritative and authoritative != self.text:
                starts_with_stream = authoritative.startswith(self.text)
                delta = authoritative[len(self.text) :] if starts_with_stream else authoritative
                self.text = authoritative
                self._emit(build_node_message_delta(delta, authoritative, force=not starts_with_stream))
            return
        if item_type == "reasoning" and completed:
            self._complete_reasoning(item)
            return
        if item_type not in TOOL_ITEM_TYPES:
            return
        if completed:
            self._tool_end(item)
        else:
            self._tool_start(item)

    def _message_delta(self, delta: str) -> None:
        if not delta:
            return
        self.text += delta
        self._emit(build_node_message_delta(delta, self.text))

    def _thinking_delta(self, item_id: str, delta: str) -> None:
        if not delta:
            return
        self._reasoning_items[item_id] = self._reasoning_items.get(item_id, "") + delta
        self.thinking_text += delta
        self._emit(build_node_thinking_delta(delta, self.thinking_text, provider="codex"))

    def _complete_reasoning(self, item: dict[str, Any]) -> None:
        item_id = str(item.get("id") or "reasoning")
        streamed = self._reasoning_items.get(item_id, "")
        if streamed:
            return
        blocks = item.get("summary")
        if not isinstance(blocks, list) or not blocks:
            blocks = item.get("content")
        if not isinstance(blocks, list):
            return
        text = "\n".join(str(block or "") for block in blocks if str(block or ""))
        if text:
            self._thinking_delta(item_id, text)

    def _tool_start(self, item: dict[str, Any]) -> None:
        call_id = self._required_item_id(item)
        if call_id in self._tool_started_at:
            return
        self._tool_started_at[call_id] = time.monotonic()
        event = {
            "type": "tool_call_start",
            "name": tool_name(item),
            "call_id": call_id,
            "provider": "codex",
            "arguments": tool_arguments(item),
            "status": "running",
        }
        self._remember_tool_event(event)
        self._emit_tool(event)

    def _tool_end(self, item: dict[str, Any]) -> None:
        call_id = self._required_item_id(item)
        if call_id not in self._tool_started_at:
            self._tool_start(item)
        started_at = self._tool_started_at.pop(call_id)
        duration = item.get("durationMs")
        duration_ms = int(round(
            float(duration)
            if isinstance(duration, (int, float)) and not isinstance(duration, bool) and duration >= 0
            else max(0.0, (time.monotonic() - started_at) * 1000.0)
        ))
        status = tool_status(item.get("status"))
        preview = tool_result_preview(item, streamed_output=self._tool_outputs.get(call_id, ""))
        error = tool_error(item)
        event: dict[str, Any] = {
            "type": "tool_call_end",
            "name": tool_name(item),
            "call_id": call_id,
            "provider": "codex",
            "arguments": tool_arguments(item),
            "status": status,
            "duration_ms": duration_ms,
            "result_preview": preview[:4000],
            "result_chars": len(preview),
            "result_preview_truncated": len(preview) > 4000,
        }
        if error:
            event["error"] = error
        self._remember_tool_event(event)
        self._emit_tool(event)

    def _runtime_notice(self, method: str, params: dict[str, Any]) -> None:
        message = params.get("message") or params.get("summary")
        if not message and method == "agentpark/serverRequestDeclined":
            message = f"Codex server request declined: {params.get('requestMethod')}"
        if message:
            self._emit({"type": "runtime_notice", "source": "codex", "stage": method, "message": str(message)})

    def _provider_request_completed(
        self,
        *,
        usage: Any,
        response_id: Any = "",
        responses_mode: str,
    ) -> None:
        self._provider_request_index += 1
        request_index = self._provider_request_index
        normalized_response_id = str(response_id or "").strip()
        summary = {
            "request_index": request_index,
            "request_api": "responses",
            "responses_mode": responses_mode,
            "requested_responses_mode": "codex_app_server",
            "stream": True,
        }
        if normalized_response_id:
            summary["response_id"] = normalized_response_id
        self._emit_provider_request_notice(PROVIDER_REQUEST_SUMMARY_STAGE, summary)

        completion: dict[str, Any] = {
            "request_index": request_index,
            "request_api": "responses",
        }
        normalized_usage = _provider_usage(usage)
        if normalized_usage:
            completion["usage"] = normalized_usage
        if normalized_response_id:
            completion["response_id"] = normalized_response_id
        self.provider_requests.append(dict(completion))
        self._emit_provider_request_notice(PROVIDER_REQUEST_COMPLETED_STAGE, completion)

    def _emit_provider_request_notice(self, stage: str, payload: dict[str, Any]) -> None:
        self._emit(
            {
                "type": "runtime_notice",
                "source": "codex_app_server",
                "stage": stage,
                "provider": self.provider_id,
                "message": json.dumps(payload, ensure_ascii=False, sort_keys=True),
            }
        )

    def _provider_gateway_request(self, params: dict[str, Any]) -> None:
        payload = dict(params)
        self.provider_gateway_requests.append(payload)
        self._emit(
            {
                "type": "runtime_notice",
                "source": "codex_provider_gateway",
                "stage": "provider_gateway_request",
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

    @staticmethod
    def _required_item_id(item: dict[str, Any]) -> str:
        item_id = str(item.get("id") or "").strip()
        if not item_id:
            raise ValueError(f"Codex tool item {item.get('type')!r} has no id.")
        return item_id


def _provider_usage(raw: Any) -> dict[str, int]:
    if not isinstance(raw, dict):
        return {}
    fields = {
        "input_tokens": ("inputTokens", "input_tokens"),
        "output_tokens": ("outputTokens", "output_tokens"),
        "total_tokens": ("totalTokens", "total_tokens"),
        "cached_input_tokens": ("cachedInputTokens", "cached_input_tokens"),
        "cache_write_input_tokens": ("cacheWriteInputTokens", "cache_write_input_tokens"),
        "reasoning_output_tokens": ("reasoningOutputTokens", "reasoning_output_tokens"),
    }
    usage: dict[str, int] = {}
    for normalized_name, source_names in fields.items():
        for source_name in source_names:
            value = raw.get(source_name)
            if isinstance(value, bool) or value is None:
                continue
            try:
                usage[normalized_name] = max(0, int(value))
            except (TypeError, ValueError):
                continue
            break
    return usage


__all__ = ["CodexLiveBridge"]
