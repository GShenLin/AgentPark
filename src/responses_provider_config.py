from __future__ import annotations

from typing import Any


OPENAI_REASONING_SUMMARY_VALUES = {"auto", "concise", "detailed", "disabled"}
RESPONSES_COMPACTION_LIMIT_KEYS = (
    "toolContextCompactionEveryToolCalls",
    "toolContextCompactionInputTokens",
    "toolContextCompactionCurrentInputTokens",
    "toolContextCompactionOutputTokens",
)
RESPONSES_REQUIRED_FIELDS = (
    "toolResultSubmissionMaxChars",
    "toolContextCompactionEnabled",
)


def validate_responses_provider_config(
    provider_name: str,
    provider: dict[str, Any],
    provider_type: str,
) -> None:
    if provider.get("responsesApi") is not True:
        return
    _require_fields(provider_name, provider)
    _validate_submission_limit(provider_name, provider)
    _validate_compaction_contract(provider_name, provider)
    _validate_session_durability_contract(provider_name, provider)
    _validate_openai_responses_contract(provider_name, provider, provider_type)


def _validate_session_durability_contract(
    provider_name: str,
    provider: dict[str, Any],
) -> None:
    ledger_enabled = provider.get("agentStepLedgerEnabled", False)
    if not isinstance(ledger_enabled, bool):
        raise ValueError(
            f"Provider '{provider_name}' has invalid agentStepLedgerEnabled; expected a boolean."
        )
    compaction_enabled = provider.get("sessionContextCompactionEnabled", False)
    if not isinstance(compaction_enabled, bool):
        raise ValueError(
            f"Provider '{provider_name}' has invalid sessionContextCompactionEnabled; expected a boolean."
        )
    for key, default in (
        ("sessionContextCompactionThresholdPercent", 80),
        ("sessionContextCompactionRetainPercent", 16),
    ):
        value = provider.get(key, default)
        if not isinstance(value, int) or isinstance(value, bool) or not 1 <= value <= 100:
            raise ValueError(
                f"Provider '{provider_name}' has invalid {key}; expected an integer between 1 and 100."
            )
    max_attempts = provider.get("sessionContextCompactionMaxAttempts", 3)
    if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or not 1 <= max_attempts <= 5:
        raise ValueError(
            f"Provider '{provider_name}' has invalid sessionContextCompactionMaxAttempts; "
            "expected an integer between 1 and 5."
        )
    context_window = provider.get("modelContextWindowTokens")
    if compaction_enabled and (
        not isinstance(context_window, int)
        or isinstance(context_window, bool)
        or context_window <= 0
    ):
        raise ValueError(
            f"Provider '{provider_name}' enables session context compaction without a positive "
            "modelContextWindowTokens integer."
        )


def _require_fields(provider_name: str, provider: dict[str, Any]) -> None:
    for key in RESPONSES_REQUIRED_FIELDS:
        if key not in provider:
            raise ValueError(
                f"Provider '{provider_name}' has responsesApi=true but missing required field {key}."
            )
    if not isinstance(provider.get("toolContextCompactionEnabled"), bool):
        raise ValueError(
            f"Provider '{provider_name}' has invalid toolContextCompactionEnabled; "
            "expected a boolean."
        )


def _validate_submission_limit(provider_name: str, provider: dict[str, Any]) -> None:
    value = provider.get("toolResultSubmissionMaxChars")
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(
            f"Provider '{provider_name}' has invalid toolResultSubmissionMaxChars; "
            "expected a positive integer."
        )


def _validate_compaction_contract(
    provider_name: str,
    provider: dict[str, Any],
) -> None:
    for key in RESPONSES_COMPACTION_LIMIT_KEYS:
        value = provider.get(key, 0)
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            raise ValueError(
                f"Provider '{provider_name}' has invalid {key}; "
                "expected a non-negative integer."
            )

    context_window_tokens = provider.get("modelContextWindowTokens")
    context_percent = provider.get("toolContextCompactionContextPercent")
    if context_window_tokens is not None and (
        not isinstance(context_window_tokens, int)
        or isinstance(context_window_tokens, bool)
        or context_window_tokens <= 0
    ):
        raise ValueError(
            f"Provider '{provider_name}' has invalid modelContextWindowTokens; "
            "expected a positive integer."
        )
    if context_percent is not None:
        _validate_context_percent(
            provider_name,
            provider,
            context_window_tokens=context_window_tokens,
            context_percent=context_percent,
        )
    elif (
        context_window_tokens is not None
        and provider.get("toolContextCompactionCurrentInputTokens", 0)
        > context_window_tokens
    ):
        raise ValueError(
            f"Provider '{provider_name}' has toolContextCompactionCurrentInputTokens "
            "greater than modelContextWindowTokens."
        )

    replacement_limit = provider.get("toolContextCompactionReplacementMaxChars")
    if replacement_limit is not None and (
        not isinstance(replacement_limit, int)
        or isinstance(replacement_limit, bool)
        or replacement_limit < 4000
    ):
        raise ValueError(
            f"Provider '{provider_name}' has invalid toolContextCompactionReplacementMaxChars; "
            "expected an integer greater than or equal to 4000."
        )

def _validate_context_percent(
    provider_name: str,
    provider: dict[str, Any],
    *,
    context_window_tokens: object,
    context_percent: object,
) -> None:
    if (
        not isinstance(context_percent, int)
        or isinstance(context_percent, bool)
        or context_percent < 1
        or context_percent > 100
    ):
        raise ValueError(
            f"Provider '{provider_name}' has invalid toolContextCompactionContextPercent; "
            "expected an integer between 1 and 100."
        )
    if context_window_tokens is None:
        raise ValueError(
            f"Provider '{provider_name}' sets toolContextCompactionContextPercent "
            "without modelContextWindowTokens."
        )
    if provider.get("toolContextCompactionCurrentInputTokens", 0) != 0:
        raise ValueError(
            f"Provider '{provider_name}' must set "
            "toolContextCompactionCurrentInputTokens=0 when "
            "toolContextCompactionContextPercent is configured."
        )


def _validate_openai_responses_contract(
    provider_name: str,
    provider: dict[str, Any],
    provider_type: str,
) -> None:
    if provider_type not in {"openai", "grok", "deepseek"}:
        return
    if provider_type in {"openai", "deepseek"}:
        _validate_openai_reasoning_summary(provider_name, provider)
    if "responsesReplayReasoningItems" not in provider:
        raise ValueError(
            f"Provider '{provider_name}' has responsesApi=true but missing required field "
            "responsesReplayReasoningItems."
        )
    if not isinstance(provider.get("responsesReplayReasoningItems"), bool):
        raise ValueError(
            f"Provider '{provider_name}' has invalid responsesReplayReasoningItems; "
            "expected a boolean."
        )
def _validate_openai_reasoning_summary(
    provider_name: str,
    provider: dict[str, Any],
) -> None:
    if "reasoningSummary" not in provider:
        return
    value = provider.get("reasoningSummary")
    if value is None or value == "":
        provider.pop("reasoningSummary", None)
        return
    if not isinstance(value, str):
        raise ValueError(
            f"Provider '{provider_name}' has invalid reasoningSummary; "
            "expected auto, concise, detailed, or disabled."
        )
    summary = value.strip().lower()
    if summary not in OPENAI_REASONING_SUMMARY_VALUES:
        raise ValueError(
            f"Provider '{provider_name}' has invalid reasoningSummary; "
            "expected auto, concise, detailed, or disabled."
        )
    provider["reasoningSummary"] = summary
