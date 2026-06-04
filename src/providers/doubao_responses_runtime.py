import json
from typing import Callable

from src.service_host import HostBoundService
from src.tool_call_protocol import to_openai_tool_call


class DoubaoResponsesRuntime(HostBoundService):
    def _send_via_responses(
        self,
        *,
        messages,
        active_tools,
        run_tools,
        thinking_mode,
        web_search_mode,
        stream_handler: Callable[[object, object], None] | None = None,
    ):
        base_url = self.config["baseUrl"].rstrip("/")
        url = f"{base_url}/responses"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        max_retries = int(self.config.get("maxRetries", 3))
        retry_delay = float(self.config.get("retryDelaySec", 1))

        tools_payload = self._build_responses_tools(active_tools, web_search_mode)
        current_input = self._build_responses_input(messages)
        previous_response_id = ""
        stream_last_text = ""
        stream_callback = stream_handler if callable(stream_handler) else None
        use_stream = callable(stream_handler)

        def _on_responses_stream(delta_text: object, full_text: object) -> None:
            nonlocal stream_last_text
            if full_text is None:
                stream_last_text = stream_last_text + str(delta_text or "")
            else:
                stream_last_text = str(full_text or "")
            self._emit_stream_text(stream_callback, delta_text, stream_last_text)

        while True:
            payload = {
                "model": self.config["model"],
                "input": current_input,
            }
            if previous_response_id:
                payload["previous_response_id"] = previous_response_id
            if tools_payload:
                payload["tools"] = tools_payload
            if thinking_mode in {"enabled", "disabled", "auto"}:
                payload["thinking"] = {"type": thinking_mode}
            if use_stream:
                payload["stream"] = True

            payload_json = json.dumps(payload, ensure_ascii=False)
            if use_stream:
                result = self._stream_responses_with_retry(
                    endpoint="responses",
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                    stream_handler=_on_responses_stream,
                )
            else:
                result = self._post_json_with_retry(
                    endpoint="responses",
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                )

            content, function_calls, response_id = self._parse_responses_output_envelopes(result)
            if function_calls:
                display_tool_calls = [to_openai_tool_call(call) for call in function_calls]
                self.Message("assistant", content, tool_calls=display_tool_calls)
                if not run_tools:
                    return {
                        "type": "function_call",
                        "function": display_tool_calls[0]["function"],
                        "tool_calls": display_tool_calls,
                    }

                followup_items = []
                for execution in self._execute_tool_call_envelopes_parallel(function_calls):
                    self.Message(
                        "tool",
                        execution.cleaned_result,
                        tool_call_id=execution.call_id,
                        name=execution.func_name,
                    )
                    non_retry_warn = self._build_non_retryable_tool_warning(
                        execution.func_name,
                        execution.cleaned_result,
                    )
                    if non_retry_warn:
                        self.Message("system", non_retry_warn)

                    image_data = execution.image_data
                    if image_data:
                        self._inject_image_message(
                            image_data.get("path"),
                            base64_data=image_data.get("base64"),
                        )

                    call_id = str(execution.call_id or "").strip()
                    if call_id:
                        followup_items.append(
                            {
                                "type": "function_call_output",
                                "call_id": call_id,
                                "output": self._ensure_json_text(execution.cleaned_result),
                            }
                        )

                if not response_id or not followup_items:
                    return content or "Error: invalid function call continuation in Responses API."

                previous_response_id = response_id
                current_input = followup_items
                continue

            if content:
                self.Message("assistant", content)
                return content
            if use_stream and stream_last_text:
                self.Message("assistant", stream_last_text)
                return stream_last_text
            self.Message("assistant", content)
            return json.dumps(result, ensure_ascii=False)
