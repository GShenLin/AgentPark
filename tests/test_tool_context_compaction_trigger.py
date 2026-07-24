import pytest

from src.tool_context_compaction_trigger import ToolContextCompactionLimits
from src.tool_context_compaction_trigger import ToolContextCompactionWindow


def _limits(
    *,
    tool_calls=0,
    input_tokens=0,
    current_input_tokens=0,
    output_tokens=0,
    **extra,
):
    config = {
        "toolContextCompactionEveryToolCalls": tool_calls,
        "toolContextCompactionInputTokens": input_tokens,
        "toolContextCompactionCurrentInputTokens": current_input_tokens,
        "toolContextCompactionOutputTokens": output_tokens,
    }
    config.update(extra)
    return ToolContextCompactionLimits.from_provider_config(config)


@pytest.mark.parametrize(
    ("limits", "tool_calls", "input_tokens", "output_tokens"),
    [
        (_limits(tool_calls=30), 30, 0, 0),
        (_limits(input_tokens=2_000_000), 0, 2_000_000, 0),
        (_limits(output_tokens=30_000), 0, 0, 30_000),
    ],
)
def test_compaction_window_triggers_when_any_enabled_limit_is_reached(
    limits,
    tool_calls,
    input_tokens,
    output_tokens,
):
    window = ToolContextCompactionWindow(regular_tool_executions=tool_calls)

    assert window.reached(
        limits,
        {
            "actual_input_tokens": input_tokens,
            "actual_output_tokens": output_tokens,
        },
    ) is True


def test_compaction_window_ignores_disabled_limits():
    window = ToolContextCompactionWindow(regular_tool_executions=29)
    limits = _limits(tool_calls=30, input_tokens=0, output_tokens=0)

    assert window.reached(
        limits,
        {
            "actual_input_tokens": 10_000_000,
            "actual_output_tokens": 100_000,
        },
    ) is False


def test_compaction_window_triggers_from_latest_actual_context_size():
    window = ToolContextCompactionWindow(regular_tool_executions=1)
    limits = _limits(current_input_tokens=50_000)

    assert window.reached(limits, {"last_actual_input_tokens": 49_999}) is False
    assert window.reached(limits, {"last_actual_input_tokens": 50_000}) is True


def test_current_context_limit_does_not_use_cumulative_input_tokens():
    window = ToolContextCompactionWindow(regular_tool_executions=1)
    limits = _limits(current_input_tokens=50_000)

    assert window.reached(
        limits,
        {
            "actual_input_tokens": 2_000_000,
            "last_actual_input_tokens": 25_000,
        },
    ) is False


def test_context_percent_derives_current_input_limit_from_model_window():
    limits = _limits(
        modelContextWindowTokens=272_000,
        toolContextCompactionContextPercent=90,
    )

    assert limits.current_input_tokens == 244_800
    assert limits.model_context_window_tokens == 272_000
    assert limits.context_percent == 90


def test_compaction_decision_reports_exact_trigger_reason_and_observed_usage():
    window = ToolContextCompactionWindow(regular_tool_executions=3)
    decision = window.evaluate(
        _limits(current_input_tokens=50_000),
        {
            "actual_input_tokens": 200_000,
            "last_actual_input_tokens": 51_000,
            "actual_output_tokens": 12_000,
        },
    )

    assert decision.reasons == ("current_input_tokens",)
    assert decision.to_payload()["observed"] == {
        "regular_tool_executions": 3,
        "input_tokens_since_reset": 200_000,
        "current_input_tokens": 51_000,
        "output_tokens_since_reset": 12_000,
    }


@pytest.mark.parametrize(
    "extra",
    [
        {"toolContextCompactionContextPercent": 90},
        {
            "modelContextWindowTokens": 272_000,
            "toolContextCompactionContextPercent": 0,
        },
        {
            "modelContextWindowTokens": 272_000,
            "toolContextCompactionContextPercent": 101,
        },
    ],
)
def test_context_percent_rejects_invalid_contract(extra):
    with pytest.raises(ValueError):
        _limits(**extra)


def test_context_percent_rejects_ambiguous_absolute_limit():
    with pytest.raises(ValueError, match="mutually exclusive"):
        _limits(
            current_input_tokens=50_000,
            modelContextWindowTokens=272_000,
            toolContextCompactionContextPercent=90,
        )


def test_compaction_window_reset_uses_current_usage_as_new_baseline():
    window = ToolContextCompactionWindow(regular_tool_executions=12)
    window.reset(
        {
            "actual_input_tokens": 2_100_000,
            "actual_output_tokens": 31_500,
        }
    )

    assert window.regular_tool_executions == 0
    assert window.usage_since_reset(
        {
            "actual_input_tokens": 2_199_999,
            "actual_output_tokens": 31_999,
        }
    ) == (99_999, 499)
    assert window.reached(
        _limits(input_tokens=100_000, output_tokens=500),
        {
            "actual_input_tokens": 2_199_999,
            "actual_output_tokens": 31_999,
        },
    ) is False
    assert window.reached(
        _limits(input_tokens=100_000, output_tokens=500),
        {
            "actual_input_tokens": 2_200_000,
            "actual_output_tokens": 32_000,
        },
    ) is True


@pytest.mark.parametrize(
    "config",
    [
        {
            "toolContextCompactionEveryToolCalls": 0,
            "toolContextCompactionInputTokens": 0,
            "toolContextCompactionCurrentInputTokens": 0,
            "toolContextCompactionOutputTokens": 0,
        },
        {
            "toolContextCompactionEveryToolCalls": 30,
            "toolContextCompactionInputTokens": -1,
            "toolContextCompactionCurrentInputTokens": 0,
            "toolContextCompactionOutputTokens": 0,
        },
    ],
)
def test_compaction_limits_reject_invalid_contract(config):
    with pytest.raises(ValueError):
        ToolContextCompactionLimits.from_provider_config(config)
