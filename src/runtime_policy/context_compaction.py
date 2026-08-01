from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.runtime_policy.contracts import RuntimePolicyValidationError


@dataclass(frozen=True)
class ContextCompactionPolicy:
    enabled: bool
    every_tool_calls: int
    input_tokens: int
    current_input_tokens: int
    output_tokens: int
    context_percent: int
    max_candidate_chars: int
    gate_prompt: str
    retry_prompt: str

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
    ) -> "ContextCompactionPolicy":
        if not isinstance(payload, dict):
            raise RuntimePolicyValidationError(f"{field} must be an object.")
        required = {
            "enabled",
            "every_tool_calls",
            "input_tokens",
            "current_input_tokens",
            "output_tokens",
            "context_percent",
            "max_candidate_chars",
            "gate_prompt",
            "retry_prompt",
        }
        missing = sorted(required - set(payload))
        unknown = sorted(set(payload) - required)
        if missing:
            raise RuntimePolicyValidationError(
                f"{field} is missing required fields: {', '.join(missing)}."
            )
        if unknown:
            raise RuntimePolicyValidationError(
                f"{field} has unknown fields: {', '.join(unknown)}."
            )
        current_input_tokens = _integer(
            payload["current_input_tokens"],
            field=f"{field}.current_input_tokens",
            minimum=0,
            maximum=10_000_000,
        )
        context_percent = _integer(
            payload["context_percent"],
            field=f"{field}.context_percent",
            minimum=0,
            maximum=100,
        )
        if current_input_tokens > 0 and context_percent > 0:
            raise RuntimePolicyValidationError(
                f"{field}.current_input_tokens and {field}.context_percent "
                "are mutually exclusive."
            )
        return cls(
            enabled=_boolean(payload["enabled"], field=f"{field}.enabled"),
            every_tool_calls=_integer(
                payload["every_tool_calls"],
                field=f"{field}.every_tool_calls",
                minimum=0,
                maximum=10_000,
            ),
            input_tokens=_integer(
                payload["input_tokens"],
                field=f"{field}.input_tokens",
                minimum=0,
                maximum=100_000_000,
            ),
            current_input_tokens=current_input_tokens,
            output_tokens=_integer(
                payload["output_tokens"],
                field=f"{field}.output_tokens",
                minimum=0,
                maximum=100_000_000,
            ),
            context_percent=context_percent,
            max_candidate_chars=_integer(
                payload["max_candidate_chars"],
                field=f"{field}.max_candidate_chars",
                minimum=1_000,
                maximum=2_000_000,
            ),
            gate_prompt=_prompt(payload["gate_prompt"], field=f"{field}.gate_prompt"),
            retry_prompt=_prompt(payload["retry_prompt"], field=f"{field}.retry_prompt"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "every_tool_calls": self.every_tool_calls,
            "input_tokens": self.input_tokens,
            "current_input_tokens": self.current_input_tokens,
            "output_tokens": self.output_tokens,
            "context_percent": self.context_percent,
            "max_candidate_chars": self.max_candidate_chars,
            "gate_prompt": self.gate_prompt,
            "retry_prompt": self.retry_prompt,
        }

    def provider_limit_overrides(self) -> dict[str, int]:
        return {
            "toolContextCompactionEveryToolCalls": self.every_tool_calls,
            "toolContextCompactionInputTokens": self.input_tokens,
            "toolContextCompactionCurrentInputTokens": self.current_input_tokens,
            "toolContextCompactionOutputTokens": self.output_tokens,
            "toolContextCompactionContextPercent": self.context_percent,
        }


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimePolicyValidationError(f"{field} must be a boolean.")
    return value


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimePolicyValidationError(f"{field} must be an integer.")
    if value < minimum or value > maximum:
        raise RuntimePolicyValidationError(
            f"{field} must be between {minimum} and {maximum}."
        )
    return value


def _prompt(value: object, *, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RuntimePolicyValidationError(f"{field} must be a non-empty string.")
    return value.strip()


__all__ = ["ContextCompactionPolicy"]
