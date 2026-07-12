import copy
import json

from src.providers.openai_responses_runtime import OpenAIResponsesRuntime
from src.providers.responses_websocket_transport import incremental_request_input
from src.grok_reasoning_effort import require_grok_reasoning_effort


class GrokResponsesRuntime(OpenAIResponsesRuntime):
    def _responses_payload_extra(self, **provider_options):
        payload = {}
        effort = require_grok_reasoning_effort(
            self.config.get("model"),
            provider_options.get("reasoning_effort"),
        )
        if effort:
            payload["reasoning"] = {"effort": effort}

        prompt_cache_key = str(self.config.get("promptCacheKey") or "").strip()
        if prompt_cache_key:
            payload["prompt_cache_key"] = prompt_cache_key
        return payload

    def _responses_required_includes(self, tools_payload) -> list[str]:
        return super()._responses_required_includes(tools_payload)

    def _validate_responses_followup_call_id(self, call_id: str) -> None:
        # xAI owns its function-call identifiers. OpenAI's fc_ item-id rule
        # is provider-specific and must not leak into the Grok contract.
        _ = call_id

    def _build_responses_payload(self, **kwargs):
        logical_payload = super()._build_responses_payload(**kwargs)
        self._grok_current_logical_responses_payload = copy.deepcopy(logical_payload)
        previous_request = getattr(self, "_grok_previous_logical_responses_payload", None)
        previous_response = getattr(self, "_grok_previous_responses_result", None)
        incremental_input = incremental_request_input(
            current_request=logical_payload,
            previous_request=previous_request,
            previous_response=previous_response,
        )
        previous_response_id = str((previous_response or {}).get("id") or "").strip()
        if not previous_response_id or incremental_input is None:
            return logical_payload
        payload = copy.deepcopy(logical_payload)
        payload["previous_response_id"] = previous_response_id
        payload["input"] = incremental_input
        return payload

    def _send_responses_request(self, **kwargs):
        result = super()._send_responses_request(**kwargs)
        logical_payload = getattr(self, "_grok_current_logical_responses_payload", None)
        if isinstance(logical_payload, dict) and isinstance(result, dict):
            self._grok_previous_logical_responses_payload = copy.deepcopy(logical_payload)
            self._grok_previous_responses_result = copy.deepcopy(result)
        return result

    def _emit_responses_runtime_notice(self, *, stage, payload):
        self._emit_provider_runtime_notice(
            message=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            stage=stage.replace("openai_responses", "grok_responses"),
        )
