import json
import random
import time
from typing import Callable

from src.providers.doubao_agent_common import _CurlHTTPError, _CurlTransportError, format_doubao_http_error
from src.providers.doubao_curl_stream_transport import DoubaoCurlStreamTransport
from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.responses_stream_events import ResponsesOutputItemAdded
from src.providers.responses_stream_events import ResponsesOutputItemDone
from src.providers.responses_stream_events import ResponsesReasoningDelta
from src.providers.responses_stream_events import ResponsesServerToolActivity
from src.providers.responses_stream_events import ResponsesStreamEvent
from src.providers.server_tool_protocol import build_server_tool_activity
from src.providers.server_tool_protocol import is_server_tool_item_type
from src.runtime_cancellation import CancellationRequested
from src.service_host import HostBoundService


class DoubaoStreamRuntime(DoubaoCurlStreamTransport, ProviderRuntimeEventMixin, HostBoundService):
    @staticmethod
    def _emit_stream_thinking(
        thinking_stream_handler: Callable[[object, object, object], None] | None,
        delta_text: object,
        full_text: object,
        provider: object = "doubao",
    ) -> None:
        if not callable(thinking_stream_handler):
            return
        try:
            thinking_stream_handler(delta_text, full_text, provider)
        except CancellationRequested:
            raise
        except Exception:
            return

    def _stream_chat_completions_once(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
        stream_handler: Callable[[object, object], None] | None,
        thinking_stream_handler: Callable[[object, object, object], None] | None = None,
    ) -> dict:
        content_chunks: list[str] = []
        thinking_chunks: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        debug_events: list[dict] = []
        for data_text in self._curl_post_sse_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
        ):
            if not data_text:
                continue
            if data_text == "[DONE]":
                debug_events.append({"index": len(debug_events), "raw": "[DONE]"})
                continue
            event = self._parse_sse_json_event(data_text, stage="chat_completions_stream_parse")
            debug_events.append(
                self._build_chat_sse_debug_event(
                    index=len(debug_events),
                    raw_data=data_text,
                    parsed_event=event,
                )
            )
            if event is None:
                continue
            choices = event.get("choices") if isinstance(event, dict) else None
            if not isinstance(choices, list):
                continue
            for choice in choices:
                if not isinstance(choice, dict):
                    continue
                delta = choice.get("delta")
                if not isinstance(delta, dict):
                    continue
                delta_text = delta.get("content")
                if isinstance(delta_text, str) and delta_text:
                    content_chunks.append(delta_text)
                    self._emit_stream_text(stream_handler, delta_text, "".join(content_chunks))
                reasoning_text = delta.get("reasoning_content")
                if isinstance(reasoning_text, str) and reasoning_text:
                    thinking_chunks.append(reasoning_text)
                    self._emit_stream_thinking(
                        thinking_stream_handler,
                        reasoning_text,
                        "".join(thinking_chunks),
                        "doubao",
                    )
                tool_calls_delta = delta.get("tool_calls")
                if not isinstance(tool_calls_delta, list):
                    continue
                for tool_item in tool_calls_delta:
                    if not isinstance(tool_item, dict):
                        continue
                    index_raw = tool_item.get("index")
                    try:
                        index = int(index_raw) if index_raw is not None else len(tool_calls_by_index)
                    except Exception:
                        index = len(tool_calls_by_index)
                    if index < 0:
                        index = len(tool_calls_by_index)
                    bucket = tool_calls_by_index.get(index)
                    if not isinstance(bucket, dict):
                        bucket = {"id": "", "type": "function", "function": {"name": "", "arguments": ""}}
                        tool_calls_by_index[index] = bucket
                    tool_id = str(tool_item.get("id") or "").strip()
                    if tool_id:
                        bucket["id"] = tool_id
                    tool_type = str(tool_item.get("type") or "").strip()
                    if tool_type:
                        bucket["type"] = tool_type
                    fn = tool_item.get("function")
                    if not isinstance(fn, dict):
                        continue
                    fn_name = str(fn.get("name") or "")
                    if fn_name:
                        bucket_fn = bucket.get("function")
                        if not isinstance(bucket_fn, dict):
                            bucket_fn = {"name": "", "arguments": ""}
                            bucket["function"] = bucket_fn
                        bucket_fn["name"] = str(bucket_fn.get("name") or "") + fn_name
                    fn_args = str(fn.get("arguments") or "")
                    if fn_args:
                        bucket_fn = bucket.get("function")
                        if not isinstance(bucket_fn, dict):
                            bucket_fn = {"name": "", "arguments": ""}
                            bucket["function"] = bucket_fn
                        bucket_fn["arguments"] = str(bucket_fn.get("arguments") or "") + fn_args
        assembled_tool_calls: list[dict] = []
        for idx in sorted(tool_calls_by_index.keys()):
            bucket = tool_calls_by_index.get(idx)
            if not isinstance(bucket, dict):
                continue
            fn = bucket.get("function")
            if not isinstance(fn, dict):
                continue
            fn_name = str(fn.get("name") or "").strip()
            if not fn_name:
                continue
            assembled_tool_calls.append({"id": str(bucket.get("id") or ""), "type": str(bucket.get("type") or "function"), "function": {"name": fn_name, "arguments": str(fn.get("arguments") or "")}})
        message = {"role": "assistant", "content": "".join(content_chunks)}
        if not assembled_tool_calls:
            parse_result = self._parse_tagged_function_calls_from_text(message["content"])
            if parse_result.diagnostics:
                self._emit_tagged_function_call_diagnostics(parse_result.diagnostics)
            message["content"] = parse_result.visible_text
            if parse_result.calls:
                assembled_tool_calls = parse_result.calls
                self._emit_stream_text(stream_handler, "", parse_result.visible_text)
        if assembled_tool_calls:
            message["tool_calls"] = assembled_tool_calls
        result = {"choices": [{"message": message}]}
        self._write_chat_sse_debug_if_needed(
            url=url,
            payload_json=payload_json,
            events=debug_events,
            assembled_message=message,
        )
        return result

    def _stream_chat_completions_with_retry(
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
        for attempt in range(max_retries + 1):
            try:
                return self._stream_chat_completions_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                    stream_handler=stream_handler,
                    thinking_stream_handler=thinking_stream_handler,
                )
            except _CurlHTTPError as e:
                status_code = int(e.status_code or 0)
                response_body = str(e.response_body or "")
                if status_code == 400:
                    self._dump_http_400_request(
                        endpoint=endpoint,
                        url=url,
                        method="POST",
                        headers=headers,
                        payload_json=payload_json,
                        status_code=status_code,
                        response_body=response_body,
                    )
                error_str = format_doubao_http_error(status_code, response_body)
                retryable = self._http_status_retryable(status_code)
                if retryable and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="chat_completions_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(error_str)
            except _CurlTransportError as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="chat_completions_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="chat_completions_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
        raise RuntimeError("Error: Max retries exceeded")
    def _stream_responses_once(
        self,
        *,
        url: str,
        headers: dict,
        payload_json: str,
        timeout_sec: float,
        stream_handler: Callable[[object, object], None] | None,
        thinking_stream_handler: Callable[[object, object, object], None] | None = None,
        item_event_handler: Callable[[ResponsesStreamEvent], None] | None = None,
    ) -> dict:
        text_chunks: list[str] = []
        thinking_chunks: list[str] = []
        saw_text_delta = False
        normalizer = OpenAIResponsesStreamEventNormalizer(provider="doubao_responses")
        function_call_buckets: dict[str, dict] = {}
        function_call_order: list[str] = []
        completed_response: dict | None = None
        def _ensure_function_call_bucket(key: str) -> dict:
            bucket = function_call_buckets.get(key)
            if not isinstance(bucket, dict):
                bucket = {"type": "function_call", "call_id": key, "name": "", "arguments": ""}
                function_call_buckets[key] = bucket
                function_call_order.append(key)
            return bucket
        def _build_synthetic_response(response_id: str = "") -> dict:
            output_items: list[dict] = []
            for key in function_call_order:
                bucket = function_call_buckets.get(key)
                if not isinstance(bucket, dict):
                    continue
                name = str(bucket.get("name") or "").strip()
                if not name:
                    continue
                output_items.append({"type": "function_call", "call_id": str(bucket.get("call_id") or key), "name": name, "arguments": str(bucket.get("arguments") or "")})
            full_text = "".join(text_chunks)
            if full_text:
                output_items.append({"type": "message", "content": [{"type": "output_text", "text": full_text}]})
            payload = {"output": output_items}
            if response_id:
                payload["id"] = response_id
            return payload
        for data_text in self._curl_post_sse_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
        ):
            if not data_text:
                continue
            if data_text == "[DONE]":
                continue
            event = self._parse_sse_json_event(data_text, stage="responses_stream_parse")
            if event is None:
                continue
            if not isinstance(event, dict):
                continue
            normalized_events = normalizer.ingest_event(event)
            for normalized_event in normalized_events:
                if callable(item_event_handler):
                    item_event_handler(normalized_event)
                if isinstance(normalized_event, ResponsesReasoningDelta) and normalized_event.delta:
                    thinking_chunks.append(normalized_event.delta)
                    self._emit_stream_thinking(
                        thinking_stream_handler,
                        normalized_event.delta,
                        "".join(thinking_chunks),
                        normalized_event.provider or "doubao_responses",
                    )
                server_tool_item = None
                server_tool_status = ""
                if isinstance(normalized_event, ResponsesOutputItemAdded) and is_server_tool_item_type(normalized_event.item_type):
                    server_tool_item = normalized_event.item
                    server_tool_status = str(normalized_event.item.get("status") or "in_progress")
                elif isinstance(normalized_event, ResponsesOutputItemDone) and is_server_tool_item_type(normalized_event.item_type):
                    server_tool_item = normalized_event.item
                    server_tool_status = str(normalized_event.item.get("status") or "completed")
                elif isinstance(normalized_event, ResponsesServerToolActivity):
                    server_tool_item = normalized_event.item
                    server_tool_status = normalized_event.status
                if server_tool_item is not None:
                    activity = build_server_tool_activity(
                        server_tool_item,
                        status=server_tool_status,
                        provider=getattr(self, "provider_name", "doubao_responses"),
                    )
                    callback = getattr(self, "tool_event_callback", None)
                    if activity is not None and callable(callback):
                        callback(activity)
            event_type = str(event.get("type") or "").strip().lower()
            if event_type in {"response.output_text.delta", "output_text.delta"}:
                delta_text = str(event.get("delta") or "")
                if delta_text:
                    saw_text_delta = True
                    text_chunks.append(delta_text)
                    self._emit_stream_text(stream_handler, delta_text, "".join(text_chunks))
                continue
            if event_type in {"response.output_text.done", "output_text.done"}:
                done_text = str(event.get("text") or "")
                if done_text:
                    current_full = "".join(text_chunks)
                    if done_text != current_full:
                        delta = done_text[len(current_full) :] if done_text.startswith(current_full) else done_text
                        self._emit_stream_text(stream_handler, delta, done_text)
                        text_chunks = [done_text]
                continue
            if event_type in {"response.output_item.added", "response.output_item.done", "response.output_item.delta"}:
                item = event.get("item")
                if not isinstance(item, dict):
                    continue
                item_type = str(item.get("type") or "").strip().lower()
                if item_type != "function_call":
                    continue
                key = str(item.get("call_id") or item.get("id") or "").strip() or f"call_{len(function_call_order)}"
                bucket = _ensure_function_call_bucket(key)
                name = str(item.get("name") or "").strip()
                if name:
                    bucket["name"] = name
                args_text = item.get("arguments")
                if args_text is not None:
                    bucket["arguments"] = str(bucket.get("arguments") or "") + str(args_text)
                if item.get("id") is not None:
                    bucket["id"] = str(item.get("id") or "")
                continue
            if event_type in {"response.function_call_arguments.delta", "function_call_arguments.delta"}:
                key = str(event.get("call_id") or event.get("item_id") or "").strip()
                if not key:
                    continue
                bucket = _ensure_function_call_bucket(key)
                delta_text = str(event.get("delta") or "")
                if delta_text:
                    bucket["arguments"] = str(bucket.get("arguments") or "") + delta_text
                continue
            if event_type in {"response.completed", "response.done"}:
                response_obj = event.get("response")
                if isinstance(response_obj, dict):
                    completed_response = response_obj
                break
        if isinstance(completed_response, dict):
            final_text, function_calls, _ = self._parse_responses_output_envelopes(completed_response)
            streamed_text = "".join(text_chunks)
            if final_text and (not saw_text_delta or final_text != streamed_text):
                delta = final_text[len(streamed_text) :] if final_text.startswith(streamed_text) else final_text
                self._emit_stream_text(stream_handler, delta, final_text)
            if final_text or function_calls:
                return completed_response
            synthesized = _build_synthetic_response(str(completed_response.get("id") or ""))
            if isinstance(synthesized.get("output"), list) and synthesized["output"]:
                return synthesized
            return completed_response
        return _build_synthetic_response()
    def _stream_responses_with_retry(
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
        item_event_handler: Callable[[ResponsesStreamEvent], None] | None = None,
    ) -> dict:
        timeout = self.config.get("timeoutMs", 60000) / 1000
        current_delay = float(retry_delay)
        for attempt in range(max_retries + 1):
            try:
                return self._stream_responses_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                    stream_handler=stream_handler,
                    thinking_stream_handler=thinking_stream_handler,
                    item_event_handler=item_event_handler,
                )
            except _CurlHTTPError as e:
                status_code = int(e.status_code or 0)
                response_body = str(e.response_body or "")
                if status_code == 400:
                    self._dump_http_400_request(
                        endpoint=endpoint,
                        url=url,
                        method="POST",
                        headers=headers,
                        payload_json=payload_json,
                        status_code=status_code,
                        response_body=response_body,
                    )
                error_str = format_doubao_http_error(status_code, response_body)
                retryable = self._http_status_retryable(status_code)
                if retryable and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="responses_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(error_str)
            except _CurlTransportError as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="responses_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
            except Exception as e:
                error_str = str(e)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=current_delay, stage="responses_retry")
                    time.sleep(current_delay + random.uniform(0, 0.5))
                    current_delay *= 2
                    continue
                raise RuntimeError(f"Error after {max_retries} retries: {error_str}")
        raise RuntimeError("Error: Max retries exceeded")
