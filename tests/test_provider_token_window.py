import pytest

from src.providers.provider_token_window import ProviderRollingTokenWindow


def test_provider_token_window_uses_combined_input_and_output_tokens():
    window = ProviderRollingTokenWindow()

    usage = window.record(
        completed_at=119.9,
        input_tokens=75,
        output_tokens=25,
        window_seconds=60,
    )

    assert usage.input_tokens == 75
    assert usage.output_tokens == 25
    assert usage.total_tokens == 100
    assert window.next_available_in_seconds(
        now=119.9,
        window_seconds=60,
        limit=100,
    ) == pytest.approx(60)


def test_provider_token_window_expires_each_request_after_rolling_sixty_seconds():
    window = ProviderRollingTokenWindow()

    window.record(completed_at=61.0, input_tokens=30, output_tokens=10, window_seconds=60)
    window.record(completed_at=119.0, input_tokens=25, output_tokens=10, window_seconds=60)

    assert window.usage(now=120.0, window_seconds=60).total_tokens == 75
    assert window.next_available_in_seconds(now=120.0, window_seconds=60, limit=70) == pytest.approx(1)
    usage = window.usage(now=121.0, window_seconds=60)
    assert usage.input_tokens == 25
    assert usage.output_tokens == 10
    assert usage.total_tokens == 35
