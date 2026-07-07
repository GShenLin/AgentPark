import json
import os
import time
from datetime import datetime
from typing import Callable

from src.providers.openai_curl_transport import OpenAICurlTransport
from src.providers.openai_transport_errors import OpenAIHttpError, OpenAITransportError
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
from src.providers.responses_stream_events import ResponsesOutputItemDone, ResponsesOutputTextDelta, ResponsesReasoningDelta, ResponsesResponseCompleted, ResponsesStreamEvent, ResponsesStreamFailure
from src.providers.responses_websocket_transport import ResponsesWebSocketTransportMixin
from src.runtime_cancellation import CancellationRequested, sleep_with_cancel
from src.service_host import HostBoundService


class OpenAITransport(ProviderStreamEmitMixin, ResponsesWebSocketTransportMixin, OpenAICurlTransport, ProviderRuntimeEventMixin, HostBoundService):
    @staticmethod
    def _http_status_retryable(status_code):
        code = int(status_code or 0)
        return code == 429 or code >= 500

    @staticmethod
    def _quota_error_non_retryable(error_text):
        text = str(error_text or "").lower()
        if not text:
            return False
        quota_markers = (
            "accountquotaexceeded",
            "insufficient_quota",
            "quota exceeded",
            "usage quota",
            "exceeded the 5-hour usage quota",
        )
        return any(marker in text for marker in quota_markers)

    def _http_error_retryable(self, status_code, error_text):
        if self._quota_error_non_retryable(error_text):
            return False
        return self._http_status_retryable(status_code)

    def _resolve_retry_policy(self):
        try:
            max_retries = int(self.config.get("maxRetries", self.config.get("max_retries", 3)))
        except Exception:
            max_retries = 3
        try:
            retry_delay = float(self.config.get("retryDelaySec", self.config.get("retry_delay_sec", 1)))
        except Exception:
            retry_delay = 1
        return max(0, max_retries), max(0, retry_delay)

    @staticmethod
    def _response_failed_error(event: dict) -> dict:
        response = event.get("response") if isinstance(event, dict) else None
        error = response.get("error") if isinstance(response, dict) else None
        if not isinstance(error, dict):
            error = event.get("error") if isinstance(event, dict) else None
        return error if isinstance(error, dict) else {}

    @staticmethod
    def _response_failed_status_code(error: dict) -> int:
        for key in ("status_code", "status", "http_status", "http_status_code"):
            value = error.get(key) if isinstance(error, dict) else None
            if value is None or value == "":
                continue
            try:
                return int(value)
            except Exception:
                continue
        code = str((error or {}).get("code") or (error or {}).get("type") or "").strip().lower()
        if code in {"rate_limit_exceeded", "rate_limit_error"}:
            return 429
        if code in {"server_error", "service_unavailable", "temporarily_unavailable"}:
            return 503
        return 0

    @staticmethod
    def _format_response_failed_error(error: dict) -> str:
        message = str((error or {}).get("message") or "").strip()
        code = str((error or {}).get("code") or (error or {}).get("type") or "").strip()
        if message and code:
            return f"{code}: {message}"
        return message or code or json.dumps(error or {}, ensure_ascii=False)

    @staticmethod
    def _emit_stream_thinking(
        thinking_stream_handler: Callable[[object, object, object], None] | None,
        delta_text: object,
        full_text: object,
        provider: object = "openai_responses",
    ) -> None:
        if not callable(thinking_stream_handler):
            return
        try:
            thinking_stream_handler(delta_text, full_text, provider)
        except CancellationRequested:
            raise
        except Exception:
            return

    @staticmethod
    def _summarize_responses_payload(payload_json):
        try:
            payload = json.loads(str(payload_json or ""))
        except Exception:
            return {"payload_parse_error": True}
        if not isinstance(payload, dict):
            return {"payload_type": type(payload).__name__}
        items = []
        for item in payload.get("input") if isinstance(payload.get("input"), list) else []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            summary = {"type": item_type, "type_present": "type" in item}
            for key in ("id", "call_id", "name", "role", "status"):
                if item.get(key) is not None:
                    summary[key] = str(item.get(key) or "")
            items.append(summary)
        return {
            "model": str(payload.get("model") or ""),
            "previous_response_id": str(payload.get("previous_response_id") or ""),
            "stream": bool(payload.get("stream")),
            "input": items,
        }

    def _write_responses_http_debug(self, *, url, payload_json, status_code, response_body):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            debug_dir = os.path.join(root, ".runtime")
            os.makedirs(debug_dir, exist_ok=True)
            entry = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "url": str(url or ""),
                "status_code": int(status_code or 0),
                "payload": self._summarize_responses_payload(payload_json),
                "response_body": str(response_body or "")[:4000],
            }
            with open(os.path.join(debug_dir, "openai_responses_debug.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            return

    def _post_json_with_retry(self, *, endpoint, url, headers, payload_json):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        max_retries, retry_delay = self._resolve_retry_policy()
        for attempt in range(max_retries + 1):
            try:
                return self._curl_post_json_once(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout,
                )
            except OpenAIHttpError as exc:
                status_code = int(exc.status_code or 0)
                error_str = f"{endpoint}: HTTP {status_code} - {exc.response_body}"
                if self._http_error_retryable(status_code, error_str) and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=retry_delay, stage="openai_post_json_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(error_str) from exc
            except OpenAITransportError as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=retry_delay, stage="openai_post_json_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc

    @staticmethod
    def _emit_responses_stream_event(handler: Callable[[ResponsesStreamEvent], None] | None, event: ResponsesStreamEvent) -> None:
        if callable(handler):
            handler(event)

    def _stream_responses_once(
        self,
        *,
        url,
        headers,
        payload_json,
        timeout_sec,
        stream_handler,
        thinking_stream_handler=None,
        item_event_handler: Callable[[ResponsesStreamEvent], None] | None = None,
    ):
        text_chunks: list[str] = []
        thinking_chunks: list[str] = []
        debug_events: list[dict] = []
        normalizer = OpenAIResponsesStreamEventNormalizer(provider="openai_responses")
        function_call_items: list[dict] = []
        function_call_by_item_id: dict[str, dict] = {}
        function_call_by_call_id: dict[str, dict] = {}
        completed_response: dict | None = None
        response_completed = False

        def _canonical_call_id_for_item(item: dict) -> str:
            item_id = str(item.get("id") or "").strip()
            call_id = str(item.get("call_id") or "").strip()
            stream_item = function_call_by_item_id.get(item_id) or function_call_by_call_id.get(call_id)
            if isinstance(stream_item, dict):
                stream_call_id = str(stream_item.get("call_id") or "").strip()
                if stream_call_id:
                    return stream_call_id
            return call_id

        def _merge_stream_call_ids(response_obj: dict) -> dict:
            output = response_obj.get("output")
            if not isinstance(output, list):
                return response_obj
            changed = False
            next_output = []
            for item in output:
                if not isinstance(item, dict) or str(item.get("type") or "").strip().lower() != "function_call":
                    next_output.append(item)
                    continue
                canonical_call_id = _canonical_call_id_for_item(item)
                if canonical_call_id and canonical_call_id != str(item.get("call_id") or "").strip():
                    item = dict(item)
                    item["call_id"] = canonical_call_id
                    changed = True
                next_output.append(item)
            if not changed:
                return response_obj
            merged = dict(response_obj)
            merged["output"] = next_output
            return merged

        def _write_sse_debug(final_payload=None) -> None:
            self._write_sse_debug_if_needed(
                endpoint="responses",
                url=url,
                payload_json=payload_json,
                events=debug_events,
                final_payload=final_payload,
                filename_prefix="openai_sse_responses",
                force=self._sse_payload_has_reasoning_or_web_search(payload_json),
            )

        def _summarize_response_payload(response_obj: dict) -> dict:
            output = response_obj.get("output") if isinstance(response_obj, dict) else None
            return {
                "id": str((response_obj or {}).get("id") or ""),
                "status": str((response_obj or {}).get("status") or ""),
                "output_count": len(output) if isinstance(output, list) else 0,
                "output": [
                    self._summarize_sse_output_item(item)
                    for item in output[:20]
                    if isinstance(item, dict)
                ]
                if isinstance(output, list)
                else [],
            }

        for data_text in self._responses_stream_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
        ):
            parsed_debug_event = None
            if data_text == "[DONE]":
                debug_events.append({"index": len(debug_events), "raw": "[DONE]"})
            else:
                try:
                    parsed_debug_event = json.loads(str(data_text or ""))
                except Exception:
                    parsed_debug_event = None
                debug_events.append(
                    self._build_sse_debug_event(
                        index=len(debug_events),
                        raw_data=data_text,
                        parsed_event=parsed_debug_event,
                    )
                )
            for event in normalizer.ingest_sse_data(data_text):
                self._emit_responses_stream_event(item_event_handler, event)
                if isinstance(event, ResponsesStreamFailure):
                    if event.event_type in {"response.failed", "response.error"} or event.status_code:
                        raise OpenAIHttpError(event.status_code, event.message)
                    raise OpenAITransportError(event.message)
                if isinstance(event, ResponsesOutputTextDelta):
                    if event.delta:
                        text_chunks.append(event.delta)
                        self._emit_stream_text(stream_handler, event.delta, "".join(text_chunks))
                    continue
                if isinstance(event, ResponsesReasoningDelta):
                    if event.delta:
                        thinking_chunks.append(event.delta)
                        self._emit_stream_thinking(
                            thinking_stream_handler,
                            event.delta,
                            "".join(thinking_chunks),
                            event.provider or "openai_responses",
                        )
                    continue
                if isinstance(event, ResponsesOutputItemDone) and event.function_call is not None:
                    item = event.function_call.to_response_item()
                    function_call_items.append(item)
                    function_call_by_item_id[item["id"]] = item
                    function_call_by_call_id[item["call_id"]] = item
                    self._emit_provider_runtime_notice(
                        message=json.dumps(
                            {
                                "event": "response.output_item.done",
                                "item_type": "function_call",
                                "item_id": item["id"],
                                "call_id": item["call_id"],
                                "name": item["name"],
                                "function_call_items_seen": len(function_call_items),
                            },
                            ensure_ascii=False,
                        ),
                        stage="openai_responses_function_call_item_done",
                    )
                    continue
                if isinstance(event, ResponsesResponseCompleted):
                    completed_response = _merge_stream_call_ids(event.response)
                    output = completed_response.get("output")
                    output_items = output if isinstance(output, list) else []
                    completed_function_calls = [
                        item
                        for item in output_items
                        if isinstance(item, dict)
                        and str(item.get("type") or "").strip().lower() == "function_call"
                    ]
                    self._emit_provider_runtime_notice(
                        message=json.dumps(
                            {
                                "event": "response.completed",
                                "response_id": event.response_id,
                                "break_after_completed": True,
                                "output_item_count": len(output_items),
                                "completed_function_call_count": len(completed_function_calls),
                                "stream_function_call_item_count": len(function_call_items),
                                "stream_text_chars": len("".join(text_chunks)),
                            },
                            ensure_ascii=False,
                        ),
                        stage="openai_responses_completed_break",
                    )
                    response_completed = True
                    break
            if response_completed:
                break

        if isinstance(completed_response, dict):
            final_text, function_calls, _ = self._parse_responses_output_envelopes(completed_response)
            streamed = "".join(text_chunks)
            if final_text and final_text != streamed:
                delta = final_text[len(streamed) :] if final_text.startswith(streamed) else final_text
                self._emit_stream_text(stream_handler, delta, final_text)
            if final_text or function_calls:
                _write_sse_debug(final_payload={"completed_response": _summarize_response_payload(completed_response)})
                return completed_response

        output_items: list[dict] = []
        for item in function_call_items:
            output_items.append(dict(item))
        full_text = "".join(text_chunks)
        if full_text:
            output_items.append({"type": "message", "content": [{"type": "output_text", "text": full_text}]})
        synthetic = {"output": output_items}
        _write_sse_debug(final_payload={"synthetic_response": _summarize_response_payload(synthetic)})
        return synthetic

    def _stream_responses_with_retry(
        self,
        *,
        endpoint,
        url,
        headers,
        payload_json,
        stream_handler,
        thinking_stream_handler=None,
        item_event_handler: Callable[[ResponsesStreamEvent], None] | None = None,
    ):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        max_retries, retry_delay = self._resolve_retry_policy()
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
            except (OpenAIHttpError, OpenAITransportError) as exc:
                status_code = int(getattr(exc, "status_code", 0) or 0)
                error_str = str(exc)
                retryable = isinstance(exc, OpenAITransportError) or self._http_error_retryable(status_code, error_str)
                if retryable and attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=retry_delay, stage="openai_responses_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(f"{endpoint}: {error_str}") from exc
