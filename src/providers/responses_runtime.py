from src.providers.agent_environment_context import build_agent_environment_context
from src.providers.responses_runtime_loop import send_via_responses
from src.providers.responses_runtime_methods import ResponsesRuntimeMethods
from src.providers.tool_feedback import ToolFeedbackMixin
from src.service_host import HostBoundService


class ResponsesRuntime(ResponsesRuntimeMethods, ToolFeedbackMixin, HostBoundService):
    def _supports_responses_api(self) -> bool:
        value = self.config.get("responsesApi")
        if value is None:
            return False
        if not isinstance(value, bool):
            raise ValueError("provider.responsesApi must be a boolean.")
        return value

    def _require_responses_api(self, feature_name: str) -> None:
        if self._supports_responses_api():
            return
        provider = str(getattr(self, "provider_name", "") or "").strip() or "provider"
        config = getattr(self, "config", None)
        provider_type = ""
        if isinstance(config, dict):
            provider_type = str(config.get("type") or "").strip()
        type_suffix = f" ({provider_type})" if provider_type else ""
        raise ValueError(
            f"Feature '{feature_name}' is not available for provider '{provider}'{type_suffix}. "
            f"Disable {feature_name} on this node or choose a provider whose feature matrix supports it."
        )

    def _send_via_responses(
        self,
        *,
        messages,
        active_tools,
        run_tools,
        regular_active_tools=None,
        web_search_mode="disabled",
        stream_handler=None,
        thinking_stream_handler=None,
        **provider_options,
    ):
        return send_via_responses(
            self,
            messages=messages,
            active_tools=active_tools,
            regular_active_tools=regular_active_tools,
            run_tools=run_tools,
            web_search_mode=web_search_mode,
            stream_handler=stream_handler,
            thinking_stream_handler=thinking_stream_handler,
            **provider_options,
        )
