from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module
from typing import Any

from src.config_loader import ConfigLoader


@dataclass(frozen=True)
class ProviderRegistration:
    provider_type: str
    module: str
    class_name: str

    def load_class(self) -> type:
        module = import_module(self.module)
        provider_class = getattr(module, self.class_name, None)
        if not isinstance(provider_class, type):
            raise TypeError(
                f"Provider registration {self.provider_type!r} does not resolve to a class: "
                f"{self.module}.{self.class_name}"
            )
        return provider_class


PROVIDER_REGISTRATIONS: dict[str, ProviderRegistration] = {
    registration.provider_type: registration
    for registration in (
        ProviderRegistration("gemini", "src.providers.gemini_agent", "GeminiAgent"),
        ProviderRegistration("doubao", "src.providers.doubao_agent", "DouBaoAgent"),
        ProviderRegistration("claude", "src.providers.claude_agent", "ClaudeAgent"),
        ProviderRegistration("deepseek", "src.providers.deepseek_agent", "DeepSeekAgent"),
        ProviderRegistration("kimi", "src.providers.kimi_agent", "KimiAgent"),
        ProviderRegistration("hyper3d", "src.providers.hyper3d_agent", "Hyper3DAgent"),
        ProviderRegistration("openai", "src.providers.openai_agent", "OpenAIAgent"),
        ProviderRegistration("grok", "src.providers.grok_agent", "GrokAgent"),
        ProviderRegistration("zhipu", "src.providers.zhipu_agent", "ZhipuAgent"),
    )
}


def create_agent(
    provider_id: object,
    memory_file_path: str | None = None,
    system_prompt: str | None = None,
    internal_memory_enabled: bool = True,
) -> Any:
    normalized_provider_id = str(provider_id)
    config = ConfigLoader().get_provider_config(normalized_provider_id)
    provider_type = str(config.get("type") or "").strip()
    registration = PROVIDER_REGISTRATIONS.get(provider_type)
    if registration is None:
        raise ValueError(
            f"Provider '{normalized_provider_id}' has unsupported type: {provider_type or '<empty>'}"
        )
    provider_class = registration.load_class()
    return provider_class(
        provider_id=normalized_provider_id,
        memory_file_path=memory_file_path,
        system_prompt=system_prompt,
        internal_memory_enabled=internal_memory_enabled,
    )
