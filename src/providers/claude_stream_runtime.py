"""Native Anthropic Messages SSE support for Claude."""

from __future__ import annotations

import json
import random
from typing import Callable

from src.providers.curl_transport import CurlResponse, CurlTransportError
from src.providers.curl_transport import CurlHttpTransport
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService


class ClaudeStreamRuntime(ProviderStreamEmitMixin, CurlHttpTransport, ProviderRuntimeEventMixin, HostBoundService):
    def _curl_post_sse_data_lines(self, *, url: str, headers: dict, payload_json: str, timeout_sec: float):
        try:
            for item in self._curl_post_sse_raw_lines(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__CLAUDE_HTTP_CODE__:",
            ):
                if isinstance(item, CurlResponse):
                    if item.status_code < 200 or item.status_code >= 300:
                        raise RuntimeError(f"messages: HTTP {item.status_code}: {item.body}")
                    continue
                yield item
        except CurlTransportError as exc:
            raise RuntimeError(str(exc)) from exc

    def _stream_messages_once(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
        stream_handler: Callable[[object, object], None] | None,
        thinking_stream_handler: Callable[[object, object, object], None] | None = None,
    ) -> dict:
        text_chunks: list[str] = []
        thinking_chunks: list[str] = []
        content_blocks: dict[int, dict] = {}
        tool_input_json: dict[int, list[str]] = {}
        debug_events: list[dict] = []
        for data_text in self._curl_post_sse_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
        ):
            if not data_text:
                continue
            event = self._parse_sse_json_event(data_text, stage="claude_messages_stream_parse")
            debug_events.append(
                self._build_chat_sse_debug_event(
                    index=len(debug_events),
                    raw_data=data_text,
                    parsed_event=event,
                )
            )
            if not isinstance(event, dict):
                continue
            event_type = str(event.get("type") or "").strip()
            if event_type == "content_block_start":
                index = self._event_index(event)
                block = event.get("content_block")
                if isinstance(block, dict):
                    content_blocks[index] = dict(block)
                    if str(block.get("type") or "") == "text" and block.get("text"):
                        text = str(block.get("text") or "")
                        text_chunks.append(text)
                        self._emit_stream_text(stream_handler, text, "".join(text_chunks))
                continue
            if event_type == "content_block_delta":
                index = self._event_index(event)
                delta = event.get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_type = str(delta.get("type") or "").strip()
                if delta_type == "text_delta":
                    text = str(delta.get("text") or "")
                    if text:
                        text_chunks.append(text)
                        block = content_blocks.setdefault(index, {"type": "text"})
                        block["text"] = str(block.get("text") or "") + text
                        self._emit_stream_text(stream_handler, text, "".join(text_chunks))
                elif delta_type == "thinking_delta":
                    thinking = str(delta.get("thinking") or "")
                    if thinking:
                        thinking_chunks.append(thinking)
                        block = content_blocks.setdefault(index, {"type": "thinking"})
                        block["thinking"] = str(block.get("thinking") or "") + thinking
                        self._emit_stream_thinking(
                            thinking_stream_handler,
                            thinking,
                            "".join(thinking_chunks),
                            "claude",
                        )
                elif delta_type == "signature_delta":
                    signature = str(delta.get("signature") or "")
                    if signature:
                        block = content_blocks.setdefault(index, {"type": "thinking"})
                        block["signature"] = signature
                elif delta_type == "input_json_delta":
                    partial = str(delta.get("partial_json") or "")
                    if partial:
                        tool_input_json.setdefault(index, []).append(partial)
                continue
            if event_type == "message_stop":
                break

        tool_calls = self._tool_calls_from_stream_blocks(content_blocks, tool_input_json)
        message: dict = {"role": "assistant", "content": "".join(text_chunks)}
        native_blocks = self._native_blocks_from_stream(content_blocks, tool_input_json)
        if native_blocks:
            message["_claude_content_blocks"] = native_blocks
        if tool_calls:
            message["tool_calls"] = tool_calls
        self._write_chat_sse_debug_if_needed(
            url=url,
            payload_json=payload_json,
            events=debug_events,
            assembled_message=message,
        )
        return {"choices": [{"message": message}]}

    @staticmethod
    def _native_blocks_from_stream(content_blocks: dict[int, dict], tool_input_json: dict[int, list[str]]) -> list[dict]:
        blocks: list[dict] = []
        for index in sorted(content_blocks.keys()):
            block = content_blocks.get(index)
            if not isinstance(block, dict):
                continue
            out = dict(block)
            if str(out.get("type") or "") == "tool_use":
                input_text = "".join(tool_input_json.get(index) or [])
                if input_text:
                    try:
                        out["input"] = json.loads(input_text)
                    except json.JSONDecodeError:
                        out["input"] = {}
            blocks.append(out)
        return blocks

    @staticmethod
    def _event_index(event: dict) -> int:
        try:
            value = int(event.get("index"))
        except Exception:
            value = 0
        return max(0, value)

    @staticmethod
    def _tool_calls_from_stream_blocks(content_blocks: dict[int, dict], tool_input_json: dict[int, list[str]]) -> list[dict]:
        calls: list[dict] = []
        for index in sorted(content_blocks.keys()):
            block = content_blocks.get(index)
            if not isinstance(block, dict) or str(block.get("type") or "") != "tool_use":
                continue
            name = str(block.get("name") or "").strip()
            if not name:
                continue
            input_text = "".join(tool_input_json.get(index) or [])
            if not input_text and isinstance(block.get("input"), dict):
                input_text = json.dumps(block.get("input"), ensure_ascii=False)
            calls.append(
                {
                    "id": str(block.get("id") or ""),
                    "type": "function",
                    "function": {"name": name, "arguments": input_text or "{}"},
                }
            )
        return calls

    def _stream_messages_with_retry(
        self,
        *,
        endpoint: str,
        url: str,
        headers: dict,
        payload_json: str,
        max_retries: int,
        retry_delay: float,
        stream_handler: Callable[[object, object], None] | None,
        thinking_stream_handler: Callable[[object, object, object], None] | None = None,
    ) -> dict:
        timeout = self.config.get("timeoutMs", 60000) / 1000
        current_delay = float(retry_delay)
        for attempt in range(max(0, max_retries) + 1):
            try:
                return self._stream_messages_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                    stream_handler=stream_handler,
                    thinking_stream_handler=thinking_stream_handler,
                )
            except CancellationRequested:
                raise
            except Exception as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="claude_messages_stream_retry")
                    sleep_with_cancel(current_delay + random.uniform(0, 0.5), self._cancel_source())
                    current_delay *= 2
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
        raise RuntimeError(f"{endpoint}: max retries exceeded")
