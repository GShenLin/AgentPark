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
        stream: bool,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": self.config["model"],
            "messages": messages,
        }
        if active_tools:
            payload["tools"] = active_tools
        effort = str(reasoning_effort or "").strip()
        if effort:
            payload["reasoning_effort"] = effort
        if stream:
            payload["stream"] = True
        return payload

    def _send_chat_completions(
        self,
        *,
        messages,
        active_tools,
        run_tools,
        reasoning_effort,
        stream,
        stream_handler,
    ):
        url = self._chat_completions_url()
        payload = self._build_chat_payload(
            messages=messages,
            active_tools=active_tools,
            reasoning_effort=reasoning_effort,
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
            )
        else:
            result = self._post_json_with_retry(
                endpoint="chat/completions",
                url=url,
                headers=self._chat_headers(),
                payload_json=payload_json,
            )
        return self._handle_chat_completions_result(
            result,
            run_tools=run_tools,
            reasoning_effort=reasoning_effort,
            stream=stream,
            stream_handler=stream_handler,
        )

    def _handle_chat_completions_result(self, result, *, run_tools, reasoning_effort, stream, stream_handler):
        message, selected_idx = self._pick_chat_response_message(result.get("choices") if isinstance(result, dict) else None, run_tools)
        if not isinstance(message, dict):
            return f"Error: Invalid message format in choice[{selected_idx}]"
        tool_calls = self._extract_openai_chat_tool_calls(message)
        if tool_calls:
            self.Message("assistant", message.get("content") or "", tool_calls=tool_calls)
            if not run_tools:
                return {"type": "function_call", "function": tool_calls[0]["function"], "tool_calls": tool_calls}
            executions = execute_tool_call_items_parallel(
                tool_call_items=parse_openai_tool_call_items(tool_calls, provider="openai_chat"),
                execute_tool_call_envelopes=self._execute_tool_call_envelopes_parallel,
            )
            self._append_tool_execution_messages_then_warnings(executions)
            if self._tool_context_compaction_gate_completed(executions):
                return json.dumps({"status": "tool_context_compaction_completed"}, ensure_ascii=False)
            self._notify_companion_about_failed_tool_executions(executions)
            self._run_tool_context_compaction_gate_if_needed(executions)
            append_mid_turn_user_messages(self)
            return self.Send(
                run_tools=run_tools,
                mode="chat",
                web_search="disabled",
                thinking="disabled",
                reasoning_effort=reasoning_effort,
                stream=stream,
                stream_handler=stream_handler,
            )

        content = message.get("content")
        text = "" if content is None else str(content)
        self.Message("assistant", text)
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

    def _stream_chat_completions_with_retry(self, *, endpoint, url, headers, payload_json, stream_handler):
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

    def _stream_chat_completions_once(self, *, url, headers, payload_json, timeout_sec, stream_handler):
        text_chunks: list[str] = []
        tool_calls_by_index: dict[int, dict] = {}
        for data_text in self._curl_post_sse_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
        ):
            if not data_text or data_text == "[DONE]":
                continue
            event = self._parse_sse_json_event(data_text, stage="openai_chat_completions_stream_parse")
            for choice in event.get("choices") if isinstance(event, dict) and isinstance(event.get("choices"), list) else []:
                delta = choice.get("delta") if isinstance(choice, dict) else None
                if not isinstance(delta, dict):
                    continue
                text = delta.get("content")
                if isinstance(text, str) and text:
                    text_chunks.append(text)
                    self._emit_stream_text(stream_handler, text, "".join(text_chunks))
                self._accumulate_chat_tool_call_delta(tool_calls_by_index, delta.get("tool_calls"))
        message: dict[str, Any] = {"role": "assistant", "content": "".join(text_chunks)}
        tool_calls = self._assembled_chat_tool_calls(tool_calls_by_index)
        if tool_calls:
            message["tool_calls"] = tool_calls
        return {"choices": [{"message": message}]}

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
            max(0, int(self.config.get("maxRetries", self.config.get("max_retries", 3)))),
            max(0.0, float(self.config.get("retryDelaySec", self.config.get("retry_delay_sec", 1)))),
        )

    @staticmethod
    def _openai_chat_error_retryable(status_code: object) -> bool:
        code = int(status_code or 0)
        return code == 429 or code >= 500
