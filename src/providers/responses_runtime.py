from src.providers.agent_environment_context import build_agent_environment_context
from src.providers.responses_runtime_loop import send_via_responses
from src.providers.responses_runtime_methods import ResponsesRuntimeMethods
from src.providers.tool_feedback import ToolFeedbackMixin
from src.service_host import HostBoundService


class ResponsesRuntime(ResponsesRuntimeMethods, ToolFeedbackMixin, HostBoundService):
    def _send_via_responses(
        self,
        *,
        messages,
        active_tools,
        run_tools,
        web_search_mode="disabled",
        stream_handler=None,
        **provider_options,
    ):
        return send_via_responses(
            self,
            messages=messages,
            active_tools=active_tools,
            run_tools=run_tools,
            web_search_mode=web_search_mode,
            stream_handler=stream_handler,
            **provider_options,
        )
