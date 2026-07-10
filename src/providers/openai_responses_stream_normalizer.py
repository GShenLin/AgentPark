from __future__ import annotations

import json
from typing import Any

from src.providers.responses_stream_events import ResponsesFunctionCallArgumentsDelta, ResponsesFunctionCallStreamItem, ResponsesOutputItemAdded, ResponsesOutputItemDone, ResponsesOutputTextDelta, ResponsesReasoningDelta, ResponsesResponseCompleted, ResponsesResponseCreated, ResponsesStreamEvent, ResponsesStreamFailure


class OpenAIResponsesStreamEventNormalizer:
    def __init__(self, *, provider: str = "openai_responses") -> None:
        self.provider = str(provider or "").strip() or "openai_responses"
        self._function_call_buckets: dict[str, dict[str, Any]] = {}
        self._function_call_keys_by_id: dict[str, str] = {}

    def ingest_sse_data(self, data_text: Any) -> list[ResponsesStreamEvent]:
        text = str(data_text or "")
        if not text or text == "[DONE]":
            return []
        try:
            event = json.loads(text)
        except json.JSONDecodeError as exc:
            return [
                self._failure(
                    message=f"Malformed Responses SSE event JSON: {exc}",
                    code="invalid_sse_json",
                    event_type="",
                )
            ]
        return self.ingest_event(event)

    def ingest_event(self, raw_event: Any) -> list[ResponsesStreamEvent]:
        if not isinstance(raw_event, dict):
            return [
                self._failure(
                    message=f"Responses SSE event must decode to an object, got {type(raw_event).__name__}",
                    code="invalid_sse_event",
                    event_type="",
                )
            ]
        raw_type = str(raw_event.get("type") or "").strip()
        event_type = raw_type.lower()
        if event_type == "response.created":
            response = raw_event.get("response")
            if not isinstance(response, dict):
                response = {}
            return [
                ResponsesResponseCreated(
                    response_id=str(response.get("id") or raw_event.get("response_id") or "").strip(),
                    response=dict(response),
                )
            ]
        if event_type in {"response.output_item.added", "output_item.added"}:
            return self._output_item_added(raw_event, raw_type)
        if event_type in {"response.output_text.delta", "output_text.delta"}:
            return self._output_text_delta(raw_event, raw_type)
        if "reasoning" in event_type or "thinking" in event_type:
            reasoning_delta = self._reasoning_delta(raw_event, raw_type)
            if reasoning_delta is not None:
                return [reasoning_delta]
        if event_type in {"response.function_call_arguments.delta", "function_call_arguments.delta"}:
            return self._function_call_arguments_delta(raw_event, raw_type)
        if event_type in {"response.function_call_arguments.done", "function_call_arguments.done"}:
            return self._function_call_arguments_done(raw_event, raw_type)
        if event_type in {"response.output_item.done", "output_item.done"}:
            return self._output_item_done(raw_event, raw_type)
        if event_type in {"response.completed", "response.done"}:
            response = raw_event.get("response")
            if not isinstance(response, dict):
                return [
                    self._failure(
                        message="Responses completed event is missing response object",
                        code="missing_completed_response",
                        event_type=raw_type,
                    )
                ]
            return [
                ResponsesResponseCompleted(
                    response_id=str(response.get("id") or raw_event.get("response_id") or "").strip(),
                    response=dict(response),
                )
            ]
        if event_type in {"response.failed", "response.error"}:
            return [self._provider_failure(raw_event, raw_type)]
        return []

    def _output_item_added(self, event: dict[str, Any], raw_type: str) -> list[ResponsesStreamEvent]:
        item = event.get("item")
        if not isinstance(item, dict):
            return [
                self._failure(
                    message="Responses output_item.added event is missing item object",
                    code="missing_output_item",
                    event_type=raw_type,
                )
            ]
        item_type = self._item_type(item)
        item_id = str(item.get("id") or event.get("item_id") or "").strip()
        if item_type == "function_call":
            if not item_id and not str(item.get("call_id") or "").strip():
                return [
                    self._failure(
                        message="Responses function_call output_item.added is missing id or call_id",
                        code="missing_function_call_identity",
                        event_type=raw_type,
                    )
                ]
            failure = self._merge_function_call_item(item, event=event, require_arguments=False)
            if failure is not None:
                return [failure]
            function_call = self._function_call_snapshot(item_id=item_id, call_id=str(item.get("call_id") or "").strip())
        else:
            function_call = None
        return [
            ResponsesOutputItemAdded(
                item_id=item_id,
                output_index=self._int_or_none(event.get("output_index")),
                item_type=item_type,
                item=dict(item),
                function_call=function_call,
            )
        ]

    def _output_text_delta(self, event: dict[str, Any], raw_type: str) -> list[ResponsesStreamEvent]:
        delta = event.get("delta")
        if not isinstance(delta, str):
            return [
                self._failure(
                    message="Responses output_text.delta event requires string delta",
                    code="invalid_text_delta",
                    event_type=raw_type,
                )
            ]
        return [
            ResponsesOutputTextDelta(
                delta=delta,
                item_id=str(event.get("item_id") or "").strip(),
                output_index=self._int_or_none(event.get("output_index")),
                content_index=self._int_or_none(event.get("content_index")),
            )
        ]

    def _reasoning_delta(self, event: dict[str, Any], raw_type: str) -> ResponsesReasoningDelta | None:
        delta = self._extract_reasoning_text(event)
        if not delta:
            return None
        return ResponsesReasoningDelta(
            delta=delta,
            item_id=str(event.get("item_id") or "").strip(),
            output_index=self._int_or_none(event.get("output_index")),
            content_index=self._int_or_none(event.get("content_index")),
            provider=self.provider,
            raw_event_type=raw_type,
        )

    def _function_call_arguments_delta(self, event: dict[str, Any], raw_type: str) -> list[ResponsesStreamEvent]:
        delta = event.get("delta")
        if not isinstance(delta, str):
            return [
                self._failure(
                    message="Responses function_call_arguments.delta event requires string delta",
                    code="invalid_function_call_arguments_delta",
                    event_type=raw_type,
                )
            ]
        item_id = str(event.get("item_id") or "").strip()
        call_id = str(event.get("call_id") or "").strip()
        if not item_id and not call_id:
            return [
                self._failure(
                    message="Responses function_call_arguments.delta is missing item_id or call_id",
                    code="missing_function_call_identity",
                    event_type=raw_type,
                )
            ]
        bucket = self._bucket_for_identity(item_id=item_id, call_id=call_id)
        if item_id:
            bucket["id"] = item_id
        if call_id:
            bucket["call_id"] = call_id
        bucket["arguments"] = str(bucket.get("arguments") or "") + delta
        bucket["arguments_seen"] = True
        return [
            ResponsesFunctionCallArgumentsDelta(
                item_id=str(bucket.get("id") or item_id),
                call_id=str(bucket.get("call_id") or call_id),
                delta=delta,
                arguments=str(bucket.get("arguments") or ""),
            )
        ]

    def _function_call_arguments_done(self, event: dict[str, Any], raw_type: str) -> list[ResponsesStreamEvent]:
        item_id = str(event.get("item_id") or "").strip()
        call_id = str(event.get("call_id") or "").strip()
        if not item_id and not call_id:
            return [
                self._failure(
                    message="Responses function_call_arguments.done is missing item_id or call_id",
                    code="missing_function_call_identity",
                    event_type=raw_type,
                )
            ]
        arguments = event.get("arguments")
        if not isinstance(arguments, str):
            return [
                self._failure(
                    message="Responses function_call_arguments.done event requires string arguments",
                    code="invalid_function_call_arguments",
                    event_type=raw_type,
                )
            ]
        bucket = self._bucket_for_identity(item_id=item_id, call_id=call_id)
        if item_id:
            bucket["id"] = item_id
        if call_id:
            bucket["call_id"] = call_id
        bucket["arguments"] = arguments
        bucket["arguments_seen"] = True
        return []

    def _output_item_done(self, event: dict[str, Any], raw_type: str) -> list[ResponsesStreamEvent]:
        item = event.get("item")
        if not isinstance(item, dict):
            return [
                self._failure(
                    message="Responses output_item.done event is missing item object",
                    code="missing_output_item",
                    event_type=raw_type,
                )
            ]
        item_type = self._item_type(item)
        item_id = str(item.get("id") or event.get("item_id") or "").strip()
        if item_type != "function_call":
            events: list[ResponsesStreamEvent] = [
                ResponsesOutputItemDone(
                    item_id=item_id,
                    output_index=self._int_or_none(event.get("output_index")),
                    item_type=item_type,
                    item=dict(item),
                    function_call=None,
                )
            ]
            if item_type == "reasoning":
                reasoning_delta = self._reasoning_delta(event, raw_type)
                if reasoning_delta is not None:
                    events.append(reasoning_delta)
            return events
        failure = self._merge_function_call_item(item, event=event, require_arguments=True)
        if failure is not None:
            return [failure]
        function_call = self._function_call_snapshot(
            item_id=item_id,
            call_id=str(item.get("call_id") or "").strip(),
        )
        if function_call is None:
            return [
                self._failure(
                    message="Responses function_call output_item.done could not resolve a complete function call item",
                    code="incomplete_function_call",
                    event_type=raw_type,
                )
            ]
        return [
            ResponsesOutputItemDone(
                item_id=function_call.id,
                output_index=self._int_or_none(event.get("output_index")),
                item_type=item_type,
                item=function_call.to_response_item(),
                function_call=function_call,
            )
        ]

    def _merge_function_call_item(
        self,
        item: dict[str, Any],
        *,
        event: dict[str, Any],
        require_arguments: bool,
    ) -> ResponsesStreamFailure | None:
        item_id = str(item.get("id") or event.get("item_id") or "").strip()
        call_id = str(item.get("call_id") or "").strip()
        name = str(item.get("name") or "").strip()
        arguments = item.get("arguments")
        status = str(item.get("status") or "").strip()
        if arguments is not None and not isinstance(arguments, str):
            return self._failure(
                message="Responses function_call item requires string arguments",
                code="invalid_function_call_arguments",
                event_type=str(event.get("type") or ""),
            )
        bucket = self._bucket_for_identity(item_id=item_id, call_id=call_id)
        if item_id:
            bucket["id"] = item_id
        if call_id:
            bucket["call_id"] = call_id
        if name:
            bucket["name"] = name
        if arguments is not None:
            bucket["arguments"] = arguments
            bucket["arguments_seen"] = True
        if status:
            bucket["status"] = status
        if require_arguments:
            missing = []
            if not str(bucket.get("id") or "").strip():
                missing.append("id")
            if not str(bucket.get("call_id") or "").strip():
                missing.append("call_id")
            if not str(bucket.get("name") or "").strip():
                missing.append("name")
            if not bucket.get("arguments_seen"):
                missing.append("arguments")
            if missing:
                return self._failure(
                    message="Responses function_call output_item.done is missing " + ", ".join(missing),
                    code="incomplete_function_call",
                    event_type=str(event.get("type") or ""),
                )
        return None

    def _bucket_for_identity(self, *, item_id: str, call_id: str) -> dict[str, Any]:
        key = (
            self._function_call_keys_by_id.get(item_id)
            or self._function_call_keys_by_id.get(call_id)
            or item_id
            or call_id
        )
        bucket = self._function_call_buckets.get(key)
        if not isinstance(bucket, dict):
            bucket = {
                "id": "",
                "call_id": "",
                "name": "",
                "arguments": "",
                "arguments_seen": False,
                "status": "",
            }
            self._function_call_buckets[key] = bucket
        if item_id:
            self._function_call_keys_by_id[item_id] = key
        if call_id:
            self._function_call_keys_by_id[call_id] = key
        return bucket

    def _function_call_snapshot(
        self,
        *,
        item_id: str,
        call_id: str,
    ) -> ResponsesFunctionCallStreamItem | None:
        key = self._function_call_keys_by_id.get(item_id) or self._function_call_keys_by_id.get(call_id)
        bucket = self._function_call_buckets.get(key) if key else None
        if not isinstance(bucket, dict):
            return None
        return ResponsesFunctionCallStreamItem(
            id=str(bucket.get("id") or ""),
            call_id=str(bucket.get("call_id") or ""),
            name=str(bucket.get("name") or ""),
            arguments=str(bucket.get("arguments") or ""),
            status=str(bucket.get("status") or ""),
        )

    def _provider_failure(self, event: dict[str, Any], raw_type: str) -> ResponsesStreamFailure:
        response = event.get("response") if isinstance(event.get("response"), dict) else {}
        error = response.get("error") if isinstance(response.get("error"), dict) else event.get("error")
        error_obj = error if isinstance(error, dict) else {}
        code = str(error_obj.get("code") or error_obj.get("type") or "provider_response_failed").strip()
        error_message = str(error_obj.get("message") or "").strip()
        message = f"{code}: {error_message}" if code and error_message else error_message
        if not message:
            message = json.dumps(error_obj or event, ensure_ascii=False)
        return self._failure(
            message=message,
            code=code,
            event_type=raw_type,
            status_code=self._status_code_from_error(error_obj),
        )

    def _failure(
        self,
        *,
        message: str,
        code: str,
        event_type: str,
        status_code: int = 0,
    ) -> ResponsesStreamFailure:
        return ResponsesStreamFailure(
            message=str(message or "").strip(),
            code=str(code or "responses_stream_error").strip(),
            provider=self.provider,
            event_type=str(event_type or "").strip(),
            status_code=int(status_code or 0),
        )

    @staticmethod
    def _item_type(item: dict[str, Any]) -> str:
        return str(item.get("type") or "").strip().lower()

    @classmethod
    def _extract_reasoning_text(cls, event: dict[str, Any]) -> str:
        for key in ("delta", "text", "summary_text", "reasoning_text", "reasoning_content"):
            value = event.get(key)
            if isinstance(value, str) and value:
                return value
        part = event.get("part")
        if isinstance(part, dict):
            return cls._extract_reasoning_text(part)
        summary = event.get("summary")
        if isinstance(summary, list):
            parts = []
            for item in summary:
                if isinstance(item, dict) and isinstance(item.get("text"), str):
                    parts.append(item["text"])
            if parts:
                return "".join(parts)
        item = event.get("item")
        if isinstance(item, dict):
            return cls._extract_reasoning_text(item)
        return ""

    @staticmethod
    def _int_or_none(value: Any) -> int | None:
        if value is None or value == "":
            return None
        try:
            return int(value)
        except Exception:
            return None

    @classmethod
    def _status_code_from_error(cls, error: dict[str, Any]) -> int:
        for key in ("status_code", "status", "http_status", "http_status_code"):
            value = error.get(key)
            if value is None or value == "":
                continue
            parsed = cls._int_or_none(value)
            if parsed is not None:
                return parsed
        code = str(error.get("code") or error.get("type") or "").strip().lower()
        if code in {"rate_limit_exceeded", "rate_limit_error"}:
            return 429
        if code in {"server_error", "service_unavailable", "temporarily_unavailable"}:
            return 503
        return 0
