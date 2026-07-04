from src.providers.responses_runtime import ResponsesRuntime


class DoubaoResponsesRuntime(ResponsesRuntime):
    def _send_operational_memory_gate(self, declaration):
        return self._send_responses_gate(declaration)

    def _send_tool_context_compaction_gate(self, declaration):
        return self._send_responses_gate(declaration)

    def _send_responses_gate(self, declaration):
        if self._supports_responses_api():
            return self._send_via_responses(
                messages=self._get_messages_with_memory(),
                active_tools=[declaration],
                run_tools=True,
                thinking_mode="disabled",
                web_search_mode="disabled",
            )
        return self.Send(tools=[declaration], run_tools=True, mode="chat", stream=False)

    def _responses_payload_extra(self, **provider_options):
        thinking_mode = provider_options.get("thinking_mode")
        payload = {}
        if thinking_mode in {"enabled", "disabled", "auto"}:
            payload["thinking"] = {"type": thinking_mode}
        reasoning_effort = str(provider_options.get("reasoning_effort") or "").strip()
        if reasoning_effort:
            payload["reasoning"] = {"effort": reasoning_effort}
        return payload

    def _responses_continuation_mode(self):
        value = self.config.get("responsesContinuationMode", "previous_response_id")
        text = str(value or "").strip()
        if text == "previous_response_id":
            return "previous_response_id"
        if text == "explicit_context":
            return "explicit_context"
        raise ValueError(
            "provider.responsesContinuationMode must be 'previous_response_id' or 'explicit_context'."
        )

    def _post_responses_request(self, *, url, headers, payload_json):
        return self._post_json_with_retry(
            endpoint="responses",
            url=url,
            headers=headers,
            payload_json=payload_json,
            max_retries=int(self.config.get("maxRetries", 3)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
        )

    def _stream_responses_request(self, *, url, headers, payload_json, stream_handler, item_event_handler=None):
        return self._stream_responses_with_retry(
            endpoint="responses",
            url=url,
            headers=headers,
            payload_json=payload_json,
            max_retries=int(self.config.get("maxRetries", 3)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
            stream_handler=stream_handler,
            item_event_handler=item_event_handler,
        )

    def _responses_previous_response_input(self, _continuation_items, followup_items):
        return list(followup_items)

    def _responses_requires_response_id_for_tool_followup(self) -> bool:
        return True

