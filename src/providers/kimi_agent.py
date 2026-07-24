from __future__ import annotations

from src.providers.kimi_chat_runtime import KimiChatRuntime
from src.kimi_model_contract import build_kimi_web_search_tool
from src.kimi_model_contract import has_kimi_web_search_tool
from src.providers.kimi_tool_runtime import KimiToolCallExecutionRuntime
from src.providers.openai_agent import OpenAIAgent


class KimiAgent(OpenAIAgent):
    """Moonshot Kimi Chat Completions agent with Kimi-native tool contracts."""

    def _create_chat_runtime(self):
        return KimiChatRuntime(self)

    def _create_tool_call_runtime(self):
        return KimiToolCallExecutionRuntime(self)

    def _build_chat_active_tools(self, active_tools, *, web_search_mode: str):
        tools = [dict(item) for item in active_tools if isinstance(item, dict)] if isinstance(active_tools, list) else []
        if web_search_mode == "enabled" and not has_kimi_web_search_tool(tools):
            tools.append(build_kimi_web_search_tool())
        return tools or None

    def _effective_feature_switch(self, feature_name: str, requested_mode: str | None, *, supported_default: bool) -> str:
        mode = requested_mode if requested_mode in {"enabled", "disabled", "auto"} else "disabled"
        if mode == "disabled":
            return mode
        features = self.config.get("features") if isinstance(self.config, dict) else None
        feature = features.get(feature_name) if isinstance(features, dict) else None
        supported = bool(feature.get("supported")) if isinstance(feature, dict) else bool(supported_default)
        if not supported:
            raise ValueError(f"Kimi feature '{feature_name}' is not supported by model {self.config.get('model')!r}.")
        return mode


__all__ = ["KimiAgent"]
