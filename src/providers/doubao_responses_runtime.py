from src.providers.responses_runtime import ResponsesRuntime
from src.providers.responses_input_items import build_responses_message_input_item
from src.doubao_reasoning_effort import require_doubao_reasoning_effort


class DoubaoResponsesRuntime(ResponsesRuntime):
    def _responses_request_target(self) -> tuple[str, dict[str, str]]:
        base_url = self.config["baseUrl"].rstrip("/")
        url = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.config['apiKey']}"}
        return url, headers

    def _responses_payload_extra(self, **provider_options):
        thinking_mode = provider_options.get("thinking_mode")
        payload = {}
        if thinking_mode in {"enabled", "disabled", "auto"}:
            payload["thinking"] = {"type": thinking_mode}
        reasoning_effort = str(provider_options.get("reasoning_effort") or "").strip()
        if reasoning_effort:
            effort = require_doubao_reasoning_effort(reasoning_effort)
            payload["reasoning"] = {"effort": effort}
        return payload

    def _prepare_responses_request_input(self, current_input):
        items, instructions = super()._prepare_responses_request_input(current_input)
        if instructions and self._responses_input_ends_with_assistant(items):
            items = [
                *items,
                build_responses_message_input_item(
                    role="user",
                    content=[
                        {
                            "type": "input_text",
                            "text": "Continue by following the current instructions and available tool contract.",
                        }
                    ],
                ),
            ]
        return items, instructions

    @staticmethod
    def _responses_input_ends_with_assistant(items) -> bool:
        if not isinstance(items, list) or not items:
            return False
        last = items[-1]
        return (
            isinstance(last, dict)
            and str(last.get("type") or "").strip().lower() == "message"
            and str(last.get("role") or "").strip().lower() == "assistant"
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

    def _stream_responses_request(self, *, url, headers, payload_json, stream_handler, thinking_stream_handler=None, item_event_handler=None):
        return self._stream_responses_with_retry(
            endpoint="responses",
            url=url,
            headers=headers,
            payload_json=payload_json,
            max_retries=int(self.config.get("maxRetries", 3)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
            stream_handler=stream_handler,
            thinking_stream_handler=thinking_stream_handler,
            item_event_handler=item_event_handler,
        )

    def _responses_requires_response_id_for_tool_followup(self) -> bool:
        return True

