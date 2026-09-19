from __future__ import annotations

from typing import Any


DEEPSEEK_THINKING_VALUES = {"enabled", "disabled"}
DEEPSEEK_REASONING_EFFORT_VALUES = {"high", "max"}


def validate_deepseek_provider_config(
    provider_name: str,
    provider: dict[str, Any],
) -> None:
    """Validate and normalize the DeepSeek-owned request defaults."""

    if "thinking" in provider:
        thinking = str(provider.get("thinking") or "").strip().lower()
        if thinking not in DEEPSEEK_THINKING_VALUES:
            allowed = ", ".join(sorted(DEEPSEEK_THINKING_VALUES))
            raise ValueError(
                f"Provider '{provider_name}' has invalid thinking; expected one of: {allowed}."
            )
        provider["thinking"] = thinking

    if "reasoningEffort" in provider:
        effort = str(provider.get("reasoningEffort") or "").strip().lower()
        if effort not in DEEPSEEK_REASONING_EFFORT_VALUES:
            allowed = ", ".join(sorted(DEEPSEEK_REASONING_EFFORT_VALUES))
            raise ValueError(
                f"Provider '{provider_name}' has invalid reasoningEffort; expected one of: {allowed}."
            )
        provider["reasoningEffort"] = effort

    if "maxTokens" in provider:
        max_tokens = provider.get("maxTokens")
        if isinstance(max_tokens, bool) or not isinstance(max_tokens, int) or max_tokens <= 0:
            raise ValueError(
                f"Provider '{provider_name}' has invalid maxTokens; expected a positive integer."
            )


__all__ = [
    "DEEPSEEK_REASONING_EFFORT_VALUES",
    "DEEPSEEK_THINKING_VALUES",
    "validate_deepseek_provider_config",
]
