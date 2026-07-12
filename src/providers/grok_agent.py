from src.providers.grok_responses_mapping import GrokResponsesMapping
from src.providers.grok_responses_runtime import GrokResponsesRuntime
from src.providers.openai_agent import OpenAIAgent
from src.providers.openai_transport import OpenAITransport
from src.providers.tool_call_runtime import ToolCallExecutionRuntime


class GrokAgent(OpenAIAgent):
    """Grok agent with an xAI-specific Responses contract."""

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                OpenAITransport(self),
                self._create_chat_runtime(),
                GrokResponsesMapping(self),
                ToolCallExecutionRuntime(self),
                GrokResponsesRuntime(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    def Send(
        self,
        tools=None,
        run_tools=True,
        mode="chat",
        web_search=None,
        thinking=None,
        reasoning_effort=None,
        reasoning_summary=None,
        stream=False,
        stream_handler=None,
        thinking_stream_handler=None,
    ):
        mode = str(mode or "chat").strip().lower()
        if mode not in {"chat", "imagechat"}:
            raise ValueError("Grok agent currently supports chat and imagechat modes.")
        if str(reasoning_summary or "").strip():
            raise ValueError("Grok does not support reasoning_summary.")
        return super().Send(
            tools=tools,
            run_tools=run_tools,
            mode=mode,
            web_search=web_search,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            reasoning_summary=None,
            stream=stream,
            stream_handler=stream_handler,
            thinking_stream_handler=thinking_stream_handler,
        )
