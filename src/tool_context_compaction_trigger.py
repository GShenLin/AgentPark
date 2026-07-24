from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.value_parsing import parse_optional_int_value


TOOL_CONTEXT_COMPACTION_LIMIT_FIELDS = (
    "toolContextCompactionEveryToolCalls",
    "toolContextCompactionInputTokens",
    "toolContextCompactionCurrentInputTokens",
    "toolContextCompactionOutputTokens",
)
MODEL_CONTEXT_WINDOW_FIELD = "modelContextWindowTokens"
TOOL_CONTEXT_COMPACTION_CONTEXT_PERCENT_FIELD = "toolContextCompactionContextPercent"


@dataclass(frozen=True)
class ToolContextCompactionLimits:
    tool_executions: int
    input_tokens: int
    current_input_tokens: int
    output_tokens: int
    model_context_window_tokens: int = 0
    context_percent: int = 0

    @classmethod
    def from_provider_config(cls, provider_config: dict[str, Any]) -> "ToolContextCompactionLimits":
        values: dict[str, int] = {}
        for key in TOOL_CONTEXT_COMPACTION_LIMIT_FIELDS:
            field_name = f"provider.{key}"
            if key not in provider_config:
                raise ValueError(
                    f"{field_name} is required when provider.toolContextCompactionEnabled is true."
                )
            try:
                parsed = parse_optional_int_value(
                    field_name,
                    provider_config.get(key),
                    minimum=0,
                )
            except ValueError as exc:
                raise ValueError(
                    f"{field_name} must be an integer greater than or equal to zero."
                ) from exc
            if parsed is None:
                raise ValueError(
                    f"{field_name} must be an integer greater than or equal to zero."
                )
            values[key] = parsed

        (
            current_input_tokens,
            model_context_window_tokens,
            context_percent,
        ) = _resolve_current_input_limit(
            provider_config,
            explicit_current_input_tokens=values["toolContextCompactionCurrentInputTokens"],
        )
        limits = cls(
            tool_executions=values["toolContextCompactionEveryToolCalls"],
            input_tokens=values["toolContextCompactionInputTokens"],
            current_input_tokens=current_input_tokens,
            output_tokens=values["toolContextCompactionOutputTokens"],
            model_context_window_tokens=model_context_window_tokens,
            context_percent=context_percent,
        )
        if not any(
            (
                limits.tool_executions,
                limits.input_tokens,
                limits.current_input_tokens,
                limits.output_tokens,
            )
        ):
            raise ValueError(
                "At least one tool context compaction limit must be greater than zero when "
                "provider.toolContextCompactionEnabled is true."
            )
        return limits


@dataclass(frozen=True)
class ToolContextCompactionDecision:
    reasons: tuple[str, ...]
    regular_tool_executions: int
    input_tokens_since_reset: int
    current_input_tokens: int
    output_tokens_since_reset: int
    limits: ToolContextCompactionLimits

    @property
    def reached(self) -> bool:
        return bool(self.reasons)

    def to_payload(self) -> dict[str, object]:
        return {
            "reasons": list(self.reasons),
            "observed": {
                "regular_tool_executions": self.regular_tool_executions,
                "input_tokens_since_reset": self.input_tokens_since_reset,
                "current_input_tokens": self.current_input_tokens,
                "output_tokens_since_reset": self.output_tokens_since_reset,
            },
            "limits": {
                "tool_executions": self.limits.tool_executions,
                "input_tokens": self.limits.input_tokens,
                "current_input_tokens": self.limits.current_input_tokens,
                "output_tokens": self.limits.output_tokens,
                "model_context_window_tokens": self.limits.model_context_window_tokens,
                "context_percent": self.limits.context_percent,
            },
        }


@dataclass
class ToolContextCompactionWindow:
    regular_tool_executions: int = 0
    input_tokens_baseline: int = 0
    output_tokens_baseline: int = 0

    def add_tool_executions(self, count: int) -> None:
        if isinstance(count, bool):
            raise TypeError("tool execution count must be an integer")
        normalized = int(count)
        if normalized < 0:
            raise ValueError("tool execution count must be non-negative")
        self.regular_tool_executions += normalized

    def usage_since_reset(self, totals: object) -> tuple[int, int]:
        normalized = totals if isinstance(totals, dict) else {}
        current_input = _non_negative_int(normalized.get("actual_input_tokens"))
        current_output = _non_negative_int(normalized.get("actual_output_tokens"))
        return (
            max(0, current_input - self.input_tokens_baseline),
            max(0, current_output - self.output_tokens_baseline),
        )

    def evaluate(
        self,
        limits: ToolContextCompactionLimits,
        totals: object,
    ) -> ToolContextCompactionDecision:
        input_tokens, output_tokens = self.usage_since_reset(totals)
        normalized = totals if isinstance(totals, dict) else {}
        current_input_tokens = _non_negative_int(normalized.get("last_actual_input_tokens"))
        reasons = []
        if (
            limits.tool_executions > 0
            and self.regular_tool_executions >= limits.tool_executions
        ):
            reasons.append("tool_executions")
        if limits.input_tokens > 0 and input_tokens >= limits.input_tokens:
            reasons.append("input_tokens_since_reset")
        if (
            limits.current_input_tokens > 0
            and current_input_tokens >= limits.current_input_tokens
        ):
            reasons.append("current_input_tokens")
        if limits.output_tokens > 0 and output_tokens >= limits.output_tokens:
            reasons.append("output_tokens_since_reset")
        return ToolContextCompactionDecision(
            reasons=tuple(reasons),
            regular_tool_executions=self.regular_tool_executions,
            input_tokens_since_reset=input_tokens,
            current_input_tokens=current_input_tokens,
            output_tokens_since_reset=output_tokens,
            limits=limits,
        )

    def reached(self, limits: ToolContextCompactionLimits, totals: object) -> bool:
        return self.evaluate(limits, totals).reached

    def reset(self, totals: object) -> None:
        normalized = totals if isinstance(totals, dict) else {}
        self.regular_tool_executions = 0
        self.input_tokens_baseline = _non_negative_int(normalized.get("actual_input_tokens"))
        self.output_tokens_baseline = _non_negative_int(normalized.get("actual_output_tokens"))


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool) or value is None:
        return 0
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _resolve_current_input_limit(
    provider_config: dict[str, Any],
    *,
    explicit_current_input_tokens: int,
) -> tuple[int, int, int]:
    percent_value = provider_config.get(TOOL_CONTEXT_COMPACTION_CONTEXT_PERCENT_FIELD)
    context_window_value = provider_config.get(MODEL_CONTEXT_WINDOW_FIELD)
    if percent_value is None:
        if context_window_value is not None:
            context_window_tokens = _positive_config_int(
                context_window_value,
                field_name=f"provider.{MODEL_CONTEXT_WINDOW_FIELD}",
            )
            if (
                explicit_current_input_tokens > 0
                and explicit_current_input_tokens > context_window_tokens
            ):
                raise ValueError(
                    "provider.toolContextCompactionCurrentInputTokens must not exceed "
                    f"provider.{MODEL_CONTEXT_WINDOW_FIELD}."
                )
            return explicit_current_input_tokens, context_window_tokens, 0
        return explicit_current_input_tokens, 0, 0

    if explicit_current_input_tokens > 0:
        raise ValueError(
            "provider.toolContextCompactionCurrentInputTokens and "
            f"provider.{TOOL_CONTEXT_COMPACTION_CONTEXT_PERCENT_FIELD} are mutually exclusive."
        )
    context_window_tokens = _positive_config_int(
        context_window_value,
        field_name=f"provider.{MODEL_CONTEXT_WINDOW_FIELD}",
    )
    context_percent = _positive_config_int(
        percent_value,
        field_name=f"provider.{TOOL_CONTEXT_COMPACTION_CONTEXT_PERCENT_FIELD}",
    )
    if context_percent > 100:
        raise ValueError(
            f"provider.{TOOL_CONTEXT_COMPACTION_CONTEXT_PERCENT_FIELD} must be between 1 and 100."
        )
    return (
        context_window_tokens * context_percent // 100,
        context_window_tokens,
        context_percent,
    )


def _positive_config_int(value: object, *, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer.")
    return value
