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
        if thinking_mode in {"enabled", "disabled", "auto"}:
            return {"thinking": {"type": thinking_mode}}
        return {}

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

    def _responses_tool_output(self, execution):
        return self._compact_tool_result_for_submission_if_needed(
            tool_name=execution.func_name,
            call_id=execution.call_id,
            content=execution.cleaned_result,
        )
