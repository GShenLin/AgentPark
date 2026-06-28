from src.base_agent import BaseAgent
from src.providers.openai_mapping import OpenAIResponsesMapping
from src.providers.openai_responses_runtime import OpenAIResponsesRuntime
from src.providers.openai_transport import OpenAITransport
from src.providers.tool_call_runtime import ToolCallExecutionRuntime
from src.service_host import ServiceHost
from src.switch_utils import parse_switch_mode


class OpenAIAgent(ServiceHost, BaseAgent):
    def __init__(self, provider_id="openai", memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        super().__init__(
            provider_id,
            memory_file_path=memory_file_path,
            system_prompt=system_prompt,
            internal_memory_enabled=internal_memory_enabled,
        )
        self.config = self._read_provider_config_from_file()
        self.system_prompt = system_prompt
        self._service_targets_cache = None

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                OpenAITransport(self),
                OpenAIResponsesMapping(self),
                ToolCallExecutionRuntime(self),
                OpenAIResponsesRuntime(self),
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
        stream=False,
        stream_handler=None,
    ):
        self.config = self._read_provider_config_from_file()
        _ = thinking
        if str(mode or "chat").strip().lower() not in {"chat", "imagechat"}:
            raise ValueError("OpenAI agent currently supports chat and imagechat modes.")

        messages = self._get_messages_with_memory()
        if isinstance(self.system_prompt, str) and self.system_prompt.strip():
            has_system = any((msg or {}).get("role") == "system" for msg in messages)
            if not has_system:
                messages = [{"role": "system", "content": self.system_prompt.strip()}] + messages

        effort_source = reasoning_effort
        if effort_source is None or effort_source == "":
            effort_source = self.config.get("reasoningEffort", self.config.get("reasoning_effort", ""))
        active_tools = tools if tools else (self.tool_declarations if self.tool_declarations else None)
        web_search_mode = parse_switch_mode(web_search, default="disabled")
        return self._send_via_responses(
            messages=messages,
            active_tools=active_tools,
            run_tools=run_tools,
            reasoning_effort=effort_source,
            web_search_mode=web_search_mode,
            stream_handler=stream_handler if stream and callable(stream_handler) else None,
        )
