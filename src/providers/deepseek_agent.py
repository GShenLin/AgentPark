from src.providers.deepseek_chat_runtime import DeepSeekChatRuntime
from src.providers.openai_agent import OpenAIAgent


class DeepSeekAgent(OpenAIAgent):
    def __init__(self, provider_id="deepseek", memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        super().__init__(
            provider_id=provider_id,
            memory_file_path=memory_file_path,
            system_prompt=system_prompt,
            internal_memory_enabled=internal_memory_enabled,
        )

    def _create_chat_runtime(self):
        return DeepSeekChatRuntime(self)
