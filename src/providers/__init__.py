from src.providers.gemini_agent import GeminiAgent
from src.providers.doubao_agent import DouBaoAgent
from src.providers.claude_agent import ClaudeAgent
from src.providers.hyper3d_agent import Hyper3DAgent
from src.providers.openai_agent import OpenAIAgent
from src.providers.zhipu_agent import ZhipuAgent
from src.config_loader import ConfigLoader

def create_agent(provider_id, memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
    if not isinstance(provider_id, str):
        provider_id = str(provider_id)

    config = ConfigLoader().get_provider_config(provider_id)
    agent_type = str(config.get("type") or "").strip()

    if agent_type == "gemini":
        return GeminiAgent(provider_id=provider_id, memory_file_path=memory_file_path, system_prompt=system_prompt, internal_memory_enabled=internal_memory_enabled)
    if agent_type == "doubao":
        return DouBaoAgent(provider_id=provider_id, memory_file_path=memory_file_path, system_prompt=system_prompt, internal_memory_enabled=internal_memory_enabled)
    if agent_type == "claude":
        return ClaudeAgent(provider_id=provider_id, memory_file_path=memory_file_path, system_prompt=system_prompt, internal_memory_enabled=internal_memory_enabled)
    if agent_type == "hyper3d":
        return Hyper3DAgent(provider_id=provider_id, memory_file_path=memory_file_path, system_prompt=system_prompt, internal_memory_enabled=internal_memory_enabled)
    if agent_type == "openai":
        return OpenAIAgent(provider_id=provider_id, memory_file_path=memory_file_path, system_prompt=system_prompt, internal_memory_enabled=internal_memory_enabled)
    if agent_type == "zhipu":
        return ZhipuAgent(provider_id=provider_id, memory_file_path=memory_file_path, system_prompt=system_prompt, internal_memory_enabled=internal_memory_enabled)

    raise ValueError(f"Provider '{provider_id}' has unsupported type: {agent_type or '<empty>'}")
