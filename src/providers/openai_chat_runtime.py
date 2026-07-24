from __future__ import annotations

import json
from typing import Any, Callable

from src.providers.mid_turn_user_inputs import append_mid_turn_user_messages
from src.providers.openai_curl_transport import OpenAICurlTransport
from src.providers.openai_transport_errors import OpenAIHttpError, OpenAITransportError
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.providers.tool_call_execution import execute_tool_call_items_parallel
from src.providers.tool_call_execution import parse_openai_tool_call_items
from src.providers.tool_turn_protocol import prepare_chat_completions_messages
from src.runtime_cancellation import CancellationRequested
from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService
from src.tool.tool_call_protocol import to_openai_tool_call


class OpenAIChatRuntime(ProviderStreamEmitMixin, OpenAICurlTransport, ProviderRuntimeEventMixin, HostBoundService):
    def _write_responses_http_debug(self, *, url, payload_json, status_code, response_body) -> None:
        _ = url, payload_json, status_code, response_body
        return None

    def _chat_completions_url(self) -> str:
        base_url = str(self.config["baseUrl"]).rstrip("/")
        if base_url.endswith("/chat/completions"):
            return base_url
        return f"{base_url}/chat/completions"

    def _chat_headers(self) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }

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
        thinking_type = str(thinking_mode or "").strip()
        # When thinking is disabled, omit both thinking and reasoning_effort.
        # Some OpenAI-compatible gateways (e.g. hy3) keep reasoning on solely
        # because reasoning_effort is present, even if thinking.type=disabled.
        if thinking_type in {"enabled", "auto"}:
            payload["thinking"] = {"type": thinking_type}
            effort = str(reasoning_effort or "").strip()
            if effort:
                payload["reasoning_effort"] = effort
        if stream:
            payload["stream"] = True
            payload["stream_options"] = {"include_usage": True}
        return payload

    def _send_chat_completions(
        self,
        *,
        messages,
        active_tools,
        run_tools,
        reasoning_effort,
        thinking_mode,
        web_search_mode,
        stream,
        stream_handler,
        thinking_stream_handler=None,
    ):
        url = self._chat_completions_url()
        payload = self._build_chat_payload(
            messages=messages,
            active_tools=active_tools,
            reasoning_effort=reasoning_effort,
            thinking_mode=thinking_mode,
            stream=bool(stream),
        )
        request_summary = self._emit_provider_payload_request_summary(
            payload,
            request_api="chat_completions",
            stream=bool(stream),
        )
        payload_json = json.dumps(payload, ensure_ascii=False)
        if stream:
            result = self._stream_chat_completions_with_retry(
                endpoint="chat/completions",
                url=url,
                headers=self._chat_headers(),
                payload_json=payload_json,
                stream_handler=stream_handler if callable(stream_handler) else None,
                thinking_stream_handler=thinking_stream_handler if callable(thinking_stream_handler) else None,
            )
        else:
            result = self._post_json_with_retry(
                endpoint="chat/completions",
                url=url,
                headers=self._chat_headers(),
                payload_json=payload_json,
            )
        self._emit_provider_request_completed(request_summary, result)
        return self._handle_chat_completions_result(
            result,
            run_tools=run_tools,
            reasoning_effort=reasoning_effort,
            thinking_mode=thinking_mode,
            web_search_mode=web_search_mode,
            stream=stream,
            stream_handler=stream_handler,
            thinking_stream_handler=thinking_stream_handler,
        )

    def _handle_chat_completions_result(
        self,
        result,
        *,
        run_tools,
        reasoning_effort,
        thinking_mode,
        web_search_mode,
        stream,
        stream_handler,
        thinking_stream_handler=None,
    ):
        message, selected_idx = self._pick_chat_response_message(result.get("choices") if isinstance(result, dict) else None, run_tools)
        if not isinstance(message, dict):
            return f"Error: Invalid message format in choice[{selected_idx}]"
        tool_calls = self._extract_openai_chat_tool_calls(message)
        if tool_calls:
            self.AssistantProgress(message.get("content") or "", tool_calls=tool_calls)
            self.Message(
                "assistant",
                None,
                persist=False,
                **self._assistant_tool_call_message_fields(message, tool_calls),
            )
            if not run_tools:
                return {"type": "function_call", "function": tool_calls[0]["function"], "tool_calls": tool_calls}
            executions = execute_tool_call_items_parallel(
                tool_call_items=parse_openai_tool_call_items(tool_calls, provider="openai_chat"),
                execute_tool_call_envelopes=self._execute_tool_call_envelopes_parallel,
            )
            self._append_tool_execution_messages_then_warnings(executions)
            self._tool_context_compaction_gate_completed(executions)
            self._notify_companion_about_failed_tool_executions(executions)
            self._run_tool_context_compaction_gate_if_needed(executions)
            append_mid_turn_user_messages(self)
            return self.Send(
                run_tools=run_tools,
                mode="chat",
                web_search=web_search_mode,
                thinking=thinking_mode,
                reasoning_effort=reasoning_effort,
                stream=stream,
                stream_handler=stream_handler,
                thinking_stream_handler=thinking_stream_handler,
            )

        content = message.get("content")
        text = "" if content is None else str(content)
        if self._tool_context_compaction_gate_active_now() and not self._finish_tool_context_compaction_gate_with_response(
            content
        ):
            self._retry_tool_context_compaction_gate("the model returned an empty response")
            return self.Send(
                run_tools=run_tools,
                mode="chat",
                web_search=web_search_mode,
                thinking=thinking_mode,
                reasoning_effort=reasoning_effort,
                stream=stream,
                stream_handler=stream_handler,
                thinking_stream_handler=thinking_stream_handler,
            )
        self.Message("assistant", text, **self._assistant_final_message_fields(message))
        return text

    def _post_json_with_retry(self, *, endpoint, url, headers, payload_json):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        max_retries, retry_delay = self._resolve_openai_chat_retry_policy()
        for attempt in range(max_retries + 1):
            try:
                return self._curl_post_json_once(url=url, headers=headers, payload_json=payload_json, timeout_sec=timeout)
            except OpenAIHttpError as exc:
                error_str = f"{endpoint}: HTTP {int(exc.status_code or 0)} - {exc.response_body}"
                if attempt < max_retries and self._openai_chat_error_retryable(exc.status_code):
                    self._emit_retry_notice(error=error_str, delay=retry_delay, stage="openai_chat_completions_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(error_str) from exc
            except OpenAITransportError as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=retry_delay, stage="openai_chat_completions_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
            except CancellationRequested:
                raise
        raise RuntimeError(f"{endpoint}: max retries exceeded")

    def _stream_chat_completions_with_retry(self, *, endpoint, url, headers, payload_json, stream_handler, thinking_stream_handler=None):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        max_retries, retry_delay = self._resolve_openai_chat_retry_policy()
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
            except (OpenAIHttpError, OpenAITransportError) as exc:
                error_str = str(exc)
                if attempt < max_retries:
                    self._emit_retry_notice(error=error_str, delay=retry_delay, stage="openai_chat_completions_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise RuntimeError(f"{endpoint}: Error after {max_retries} retries: {error_str}") from exc
            except CancellationRequested:
                raise
        raise RuntimeError(f"{endpoint}: max retries exceeded")

    def _stream_chat_completions_once(self, *, url, headers, payload_json, timeout_sec, stream_handler, thinking_stream_handler=None):
        text_chunks: list[str] = []
        thinking_chunks: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        debug_events: list[dict] = []
        usage: dict[str, Any] = {}
        emitted_web_search_signatures: set[str] = set()
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
            event = self._parse_sse_json_event(data_text, stage="openai_chat_completions_stream_parse")
            debug_events.append(
                self._build_chat_sse_debug_event(
                    index=len(debug_events),
                    raw_data=data_text,
                    parsed_event=event,
                )
            )
            if not isinstance(event, dict):
                continue
            if isinstance(event.get("usage"), dict):
                usage = dict(event["usage"])
            for web_search_event in self._extract_native_web_search_events(event, source="event"):
                self._emit_native_web_search_notice_once(web_search_event, emitted_web_search_signatures)
            for choice in event.get("choices") if isinstance(event, dict) and isinstance(event.get("choices"), list) else []:
                delta = choice.get("delta") if isinstance(choice, dict) else None
                if not isinstance(delta, dict):
                    continue
                for web_search_event in self._extract_native_web_search_events(choice, source="choice"):
                    self._emit_native_web_search_notice_once(web_search_event, emitted_web_search_signatures)
                for web_search_event in self._extract_native_web_search_events(delta, source="delta"):
                    self._emit_native_web_search_notice_once(web_search_event, emitted_web_search_signatures)
                text = delta.get("content")
                if isinstance(text, str) and text:
                    text_chunks.append(text)
                    self._emit_stream_text(stream_handler, text, "".join(text_chunks))
                thinking_text = self._extract_chat_thinking_delta(delta)
                if thinking_text:
                    thinking_chunks.append(thinking_text)
                    self._emit_stream_thinking(
                        thinking_stream_handler,
                        thinking_text,
                        "".join(thinking_chunks),
                        "openai_chat",
                    )
                self._accumulate_chat_tool_call_delta(tool_calls_by_index, delta.get("tool_calls"))
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_chunks)}
        tool_calls = self._assembled_chat_tool_calls(tool_calls_by_index)
        if tool_calls:
            message["tool_calls"] = tool_calls
        self._attach_stream_thinking_to_message(message, "".join(thinking_chunks))
        self._write_chat_sse_debug_if_needed(
            url=url,
            payload_json=payload_json,
            events=debug_events,
            assembled_message=message,
        )
        result: dict[str, Any] = {"choices": [{"message": message}]}
        if usage:
            result["usage"] = usage
        return result

    def _assistant_tool_call_message_fields(self, message: dict[str, Any], tool_calls: list[dict]) -> dict[str, Any]:
        _ = message
        return {"tool_calls": tool_calls}

    def _assistant_final_message_fields(self, message: dict[str, Any]) -> dict[str, Any]:
        _ = message
        return {}

    def _attach_stream_thinking_to_message(self, message: dict[str, Any], thinking_text: str) -> None:
        _ = message, thinking_text

    @classmethod
    def _extract_chat_thinking_delta(cls, delta: dict[str, Any]) -> str:
        for key in ("reasoning_content", "reasoning_text", "thinking_content", "thinking", "reasoning"):
            text = cls._chat_delta_text_value(delta.get(key))
            if text:
                return text
        return ""

    @classmethod
    def _chat_delta_text_value(cls, value: Any) -> str:
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("delta", "text", "content", "reasoning_content", "thinking"):
                text = cls._chat_delta_text_value(value.get(key))
                if text:
                    return text
        if isinstance(value, list):
            return "".join(cls._chat_delta_text_value(item) for item in value)
        return ""

    def _extract_native_web_search_events(self, payload: dict[str, Any], *, source: str) -> list[dict[str, Any]]:
        if not isinstance(payload, dict):
            return []
        events: list[dict[str, Any]] = []
        for key in ("web_search", "web_search_call", "web_search_calls", "search_results", "references", "citations"):
            if key not in payload:
                continue
            events.append(self._build_native_web_search_event(source=source, key=key, value=payload.get(key)))
        annotations = payload.get("annotations")
        if self._annotations_include_web_citations(annotations):
            events.append(self._build_native_web_search_event(source=source, key="annotations", value=annotations))
        return events

    @staticmethod
    def _annotations_include_web_citations(value: Any) -> bool:
        if not isinstance(value, list):
            return False
        for item in value:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type in {"url_citation", "web_search", "web_search_result"}:
                return True
            if isinstance(item.get("url_citation"), dict):
                return True
        return False

    def _build_native_web_search_event(self, *, source: str, key: str, value: Any) -> dict[str, Any]:
        preview = self._native_web_search_preview(value)
        return {
            "event": "native_web_search",
            "source": str(source or ""),
            "key": str(key or ""),
            "preview": preview,
        }

    @staticmethod
    def _native_web_search_preview(value: Any, limit: int = 2000) -> str:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
        if len(text) <= limit:
            return text
        return text[: limit - 3] + "..."

    def _emit_native_web_search_notice_once(self, event: dict[str, Any], emitted_signatures: set[str]) -> None:
        signature = json.dumps(event, ensure_ascii=False, sort_keys=True)
        if signature in emitted_signatures:
            return
        emitted_signatures.add(signature)
        self._emit_provider_runtime_notice(
            message=json.dumps(event, ensure_ascii=False, sort_keys=True),
            stage="openai_chat_native_web_search",
        )

    @staticmethod
    def _accumulate_chat_tool_call_delta(tool_calls_by_index: dict[int, dict], tool_calls_delta: object) -> None:
        if not isinstance(tool_calls_delta, list):
            return
        for item in tool_calls_delta:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index")) if item.get("index") is not None else len(tool_calls_by_index)
            except Exception:
                index = len(tool_calls_by_index)
            bucket = tool_calls_by_index.setdefault(index, {"id": "", "type": "function", "function": {"name": "", "arguments": ""}})
            if item.get("id"):
                bucket["id"] = str(item.get("id") or "")
            fn = item.get("function")
            if isinstance(fn, dict):
                bucket["function"]["name"] += str(fn.get("name") or "")
                bucket["function"]["arguments"] += str(fn.get("arguments") or "")

    @staticmethod
    def _assembled_chat_tool_calls(tool_calls_by_index: dict[int, dict]) -> list[dict]:
        calls = []
        for index in sorted(tool_calls_by_index):
            item = tool_calls_by_index[index]
            name = str((item.get("function") or {}).get("name") or "").strip()
            if name:
                calls.append(item)
        return calls

    def _extract_openai_chat_tool_calls(self, message) -> list[dict]:
        raw_tool_calls = message.get("tool_calls") if isinstance(message, dict) else None
        valid = [to_openai_tool_call(call) for call in parse_openai_tool_call_items(raw_tool_calls, provider="openai_chat")]
        return [call for call in valid if call]

    def _pick_chat_response_message(self, choices, run_tools):
        if not isinstance(choices, list) or not choices:
            return None, None
        if run_tools:
            for idx, choice in enumerate(choices):
                msg = (choice or {}).get("message")
                if self._extract_openai_chat_tool_calls(msg):
                    return msg, idx
        return (choices[0] or {}).get("message"), 0

    def _resolve_openai_chat_retry_policy(self) -> tuple[int, float]:
        return (
            max(0, int(self.config.get("maxRetries", 3))),
            max(0.0, float(self.config.get("retryDelaySec", 1))),
        )

    @staticmethod
    def _openai_chat_error_retryable(status_code: object) -> bool:
        code = int(status_code or 0)
        return code == 429 or code >= 500
