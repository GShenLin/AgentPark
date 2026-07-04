import json

from src.providers.provider_runtime_events import emit_provider_runtime_notice
from src.providers.responses_runtime import ResponsesRuntime


class OpenAIResponsesRuntime(ResponsesRuntime):
    def _send_tool_context_compaction_gate(self, declaration):
        return self._send_via_responses(
            messages=self._get_messages_with_memory(),
            active_tools=[declaration],
            run_tools=True,
            reasoning_effort="",
            web_search_mode="disabled",
        )

    def _responses_payload_extra(self, **provider_options):
        reasoning_effort = provider_options.get("reasoning_effort")
        if reasoning_effort:
            return {
                "reasoning": {"effort": reasoning_effort},
                "include": ["reasoning.encrypted_content"],
            }
        return {}

    def _supports_responses_api(self) -> bool:
        if "responsesApi" not in self.config:
            return False
        value = self.config.get("responsesApi")
        if not isinstance(value, bool):
            raise ValueError("provider.responsesApi must be a boolean.")
        return value

    def _responses_continuation_mode(self):
        if "responsesContinuationMode" not in self.config:
            raise ValueError(
                "provider.responsesContinuationMode is required. "
                "Set it explicitly to 'previous_response_id' or 'explicit_context'."
            )
        value = self.config.get("responsesContinuationMode")
        text = str(value or "").strip()
        if text == "previous_response_id":
            return "previous_response_id"
        if text == "explicit_context":
            return "explicit_context"
        raise ValueError(
            "provider.responsesContinuationMode must be 'previous_response_id' or 'explicit_context'."
        )

    def _responses_continuation_input_items(self, result, function_calls):
        return self._build_responses_continuation_input_items(result, function_calls)

    def _validate_responses_followup_call_id(self, call_id: str) -> None:
        if call_id.startswith("fc_"):
            raise ValueError(
                "OpenAI Responses function_call_output.call_id cannot use an output item id. "
                "Expected the call_id from the function_call item."
            )

    def _emit_responses_previous_response_missing(
        self,
        *,
        previous_response_id,
        fallback_input_item_count,
        stream,
    ) -> None:
        self._emit_responses_runtime_notice(
            stage="openai_responses_previous_response_missing",
            payload={
                "previous_response_id": previous_response_id,
                "fallback": "explicit_context",
                "fallback_input_item_count": fallback_input_item_count,
                "stream": stream,
            },
        )

    def _emit_responses_item_level_abort(self, summary):
        payload = dict(summary) if isinstance(summary, dict) else {"reason": "aborted"}
        payload["responses_mode"] = "item_level"
        self._emit_responses_runtime_notice(stage="openai_responses_item_level_abort", payload=payload)

    def _emit_responses_turn_debug(
        self,
        *,
        response_id,
        content,
        function_call_count,
        next_continuation_mode,
        request_previous_response_id,
        request_input_item_count,
        followup_item_count,
        stream,
        responses_mode="whole_response",
        requested_responses_mode="whole_response",
        responses_mode_fallback_reason="",
    ) -> None:
        payload = {
            "responses_mode": str(responses_mode or "").strip(),
            "requested_responses_mode": str(requested_responses_mode or "").strip(),
            "responses_mode_fallback_reason": str(responses_mode_fallback_reason or "").strip(),
            "response_id_present": bool(str(response_id or "").strip()),
            "response_id": str(response_id or "").strip(),
            "function_call_count": int(function_call_count or 0),
            "content_chars": len(str(content or "")),
            "content_preview": self._preview_responses_debug_text(content),
            "next_continuation_mode": str(next_continuation_mode or "").strip(),
            "request_previous_response_id_present": bool(str(request_previous_response_id or "").strip()),
            "request_previous_response_id": str(request_previous_response_id or "").strip(),
            "request_input_item_count": int(request_input_item_count or 0),
            "followup_item_count": int(followup_item_count or 0),
            "stream": bool(stream),
        }
        self._emit_responses_runtime_notice(stage="openai_responses_turn", payload=payload)

    def _emit_responses_runtime_notice(self, *, stage, payload):
        emit_provider_runtime_notice(
            getattr(self, "tool_event_callback", None),
            provider=getattr(self, "provider_name", "openai"),
            message=json.dumps(payload, ensure_ascii=False, sort_keys=True),
            stage=stage,
        )

    @staticmethod
    def _preview_responses_debug_text(text, limit=160):
        normalized = " ".join(str(text or "").split())
        if len(normalized) <= limit:
            return normalized
        return normalized[: limit - 3] + "..."
