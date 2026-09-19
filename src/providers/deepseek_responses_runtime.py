from __future__ import annotations

from src.providers.openai_responses_runtime import OpenAIResponsesRuntime


class DeepSeekResponsesRuntime(OpenAIResponsesRuntime):
    """DeepSeek Responses request fields layered on the shared Responses loop."""

    def _responses_maintenance_provider_options(self, provider_options):
        normalized_options = super()._responses_maintenance_provider_options(provider_options)
        session_gate = getattr(self, "_session_context_compaction_active_now", None)
        if callable(session_gate) and session_gate():
            # DeepSeek rejects tool_choice=required while reasoning/thinking is enabled.
            # The maintenance request is deterministic summarization, so disable
            # reasoning only for that request and restore the caller's options next turn.
            normalized_options["thinking_mode"] = "disabled"
            normalized_options["reasoning_effort"] = "none"
        return normalized_options

    def _responses_payload_extra(self, **provider_options):
        normalized_options = dict(provider_options)
        if str(normalized_options.get("thinking_mode") or "").strip().lower() == "disabled":
            normalized_options["reasoning_effort"] = "none"
        payload = super()._responses_payload_extra(**normalized_options)
        max_tokens = self.config.get("maxTokens")
        if max_tokens is not None:
            payload["max_output_tokens"] = _positive_int(max_tokens, "DeepSeek maxTokens")
        return payload


def _positive_int(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value


__all__ = ["DeepSeekResponsesRuntime"]
