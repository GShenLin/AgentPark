import json
from typing import Callable

from src.providers.openai_curl_transport import OpenAICurlTransport
from src.providers.openai_transport_errors import OpenAIHttpError, OpenAIResponseIncompleteError, OpenAITransportError
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.providers.openai_responses_http_debug import OpenAIResponsesHttpDebugMixin
from src.providers.openai_responses_stream_normalizer import OpenAIResponsesStreamEventNormalizer
from src.providers.openai_retry_transport import OpenAIRetryTransportMixin
from src.providers.response_refusal_protocol import build_response_refusal_event
from src.providers.responses_stream_events import ResponsesOutputItemAdded, ResponsesOutputItemDone, ResponsesOutputTextDelta, ResponsesReasoningDelta, ResponsesRefusalDelta, ResponsesResponseCompleted, ResponsesResponseIncomplete, ResponsesServerToolActivity, ResponsesStreamEvent, ResponsesStreamFailure
from src.providers.server_tool_protocol import build_server_tool_activity, is_server_tool_item_type
from src.providers.responses_websocket_transport import ResponsesWebSocketTransportMixin
from src.runtime_cancellation import CancellationRequested
from src.service_host import HostBoundService


class OpenAITransport(
    OpenAIRetryTransportMixin, OpenAIResponsesHttpDebugMixin, ProviderStreamEmitMixin,
    ResponsesWebSocketTransportMixin, OpenAICurlTransport, ProviderRuntimeEventMixin, HostBoundService,
):
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
        provider_type = str(self.config.get("type") or "openai").strip().lower() or "openai"
        normalizer = OpenAIResponsesStreamEventNormalizer(provider=f"{provider_type}_responses")
        streamed_output_items: list[dict] = []
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

        def _append_streamed_output_item(item: dict) -> None:
            item_id = str(item.get("id") or "").strip()
            if item_id and any(str(existing.get("id") or "").strip() == item_id for existing in streamed_output_items):
                return
            streamed_output_items.append(dict(item))

        def _merge_streamed_output(response_obj: dict) -> dict:
            completed_output = response_obj.get("output")
            completed_items = completed_output if isinstance(completed_output, list) else []
            if not streamed_output_items:
                return response_obj
            merged_output = [dict(item) for item in streamed_output_items]
            seen_ids = {
                str(item.get("id") or "").strip()
                for item in merged_output
                if str(item.get("id") or "").strip()
            }
            for item in completed_items:
                if not isinstance(item, dict):
                    merged_output.append(item)
                    continue
                item_id = str(item.get("id") or "").strip()
                if item_id and item_id in seen_ids:
                    continue
                merged_output.append(dict(item))
                if item_id:
                    seen_ids.add(item_id)
            merged = dict(response_obj)
            merged["output"] = merged_output
            return merged

        def _write_sse_debug(final_payload=None, *, failure=False):
            return self._write_sse_debug_if_needed(
                endpoint="responses",
                url=url,
                payload_json=payload_json,
                events=debug_events,
                final_payload=final_payload,
                filename_prefix="openai_sse_responses_failure" if failure else "openai_sse_responses",
                force=failure or self._sse_payload_has_reasoning_or_web_search(payload_json),
            )

        def _failure_debug_payload(event: ResponsesStreamFailure) -> dict:
            return {
                "message": event.message,
                "code": event.code,
                "provider": event.provider,
                "event_type": event.event_type,
                "status_code": event.status_code,
                "details": dict(event.details),
            }

        def _write_unexpected_failure_debug(exc: Exception):
            failure = {
                "message": str(exc),
                "code": "unexpected_responses_stream_exception",
                "exception_type": type(exc).__name__,
            }
            debug_path = _write_sse_debug(final_payload={"failure": failure}, failure=True)
            if debug_path:
                self._emit_provider_runtime_notice(
                    message=json.dumps(
                        {
                            "event": "responses_sse_failure_debug_written",
                            "code": failure["code"],
                            "path": debug_path,
                        },
                        ensure_ascii=False,
                    ),
                    stage="openai_responses_sse_failure_debug",
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

        try:
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
                    if callable(item_event_handler):
                        item_event_handler(event)
                    if isinstance(event, ResponsesStreamFailure):
                        if debug_events:
                            failed_debug_event = dict(debug_events[-1])
                            failed_debug_event["raw"] = str(data_text or "")
                            failed_debug_event["raw_length"] = len(str(data_text or ""))
                            failed_debug_event["raw_truncated"] = False
                            failed_debug_event["normalized_failure"] = _failure_debug_payload(event)
                            debug_events[-1] = failed_debug_event
                        debug_path = _write_sse_debug(
                            final_payload={"failure": _failure_debug_payload(event)},
                            failure=True,
                        )
                        if debug_path:
                            self._emit_provider_runtime_notice(
                                message=json.dumps(
                                    {
                                        "event": "responses_sse_failure_debug_written",
                                        "code": event.code,
                                        "path": debug_path,
                                    },
                                    ensure_ascii=False,
                                ),
                                stage="openai_responses_sse_failure_debug",
                            )
                        if event.event_type in {"response.failed", "response.error", "error"} or event.status_code:
                            raise OpenAIHttpError(
                                event.status_code,
                                event.message,
                                provider_code=event.code,
                            )
                        raise OpenAITransportError(event.message)
                    if isinstance(event, ResponsesResponseIncomplete):
                        incomplete_payload = {
                            "response_id": event.response_id,
                            "reason": event.reason,
                            "response": _summarize_response_payload(event.response),
                        }
                        if debug_events:
                            terminal_debug_event = dict(debug_events[-1])
                            terminal_debug_event["normalized_terminal"] = {
                                "event": event.event,
                                "response_id": event.response_id,
                                "reason": event.reason,
                            }
                            debug_events[-1] = terminal_debug_event
                        _write_sse_debug(final_payload={"incomplete_response": incomplete_payload}, failure=True)
                        raise OpenAIResponseIncompleteError(response=event.response, reason=event.reason)
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
                    if isinstance(event, ResponsesRefusalDelta):
                        callback = getattr(self, "tool_event_callback", None)
                        if callable(callback):
                            callback(
                                build_response_refusal_event(
                                    delta=event.delta,
                                    text=event.text,
                                    item_id=event.item_id,
                                    output_index=event.output_index,
                                    content_index=event.content_index,
                                    provider=event.provider,
                                    status=event.status,
                                )
                            )
                        continue
                    if isinstance(event, ResponsesOutputItemAdded) and is_server_tool_item_type(event.item_type):
                        activity = build_server_tool_activity(
                            event.item,
                            status=str(event.item.get("status") or "in_progress"),
                            provider=getattr(self, "provider_name", "openai_responses"),
                        )
                        if activity is not None:
                            callback = getattr(self, "tool_event_callback", None)
                            if callable(callback):
                                callback(activity)
                        continue
                    if isinstance(event, ResponsesServerToolActivity):
                        activity = build_server_tool_activity(
                            event.item,
                            status=event.status,
                            provider=getattr(self, "provider_name", "openai_responses"),
                        )
                        if activity is not None:
                            callback = getattr(self, "tool_event_callback", None)
                            if callable(callback):
                                callback(activity)
                        continue
                    if isinstance(event, ResponsesOutputItemDone):
                        item = event.function_call.to_response_item() if event.function_call is not None else dict(event.item)
                        _append_streamed_output_item(item)
                        if is_server_tool_item_type(event.item_type):
                            activity = build_server_tool_activity(
                                item,
                                status=str(item.get("status") or "completed"),
                                provider=getattr(self, "provider_name", "openai_responses"),
                            )
                            if activity is not None:
                                callback = getattr(self, "tool_event_callback", None)
                                if callable(callback):
                                    callback(activity)
                        if event.function_call is not None:
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
                        completed_response = _merge_stream_call_ids(_merge_streamed_output(event.response))
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
        except (OpenAIHttpError, OpenAITransportError):
            raise
        except CancellationRequested:
            raise
        except Exception as exc:
            _write_unexpected_failure_debug(exc)
            raise

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
