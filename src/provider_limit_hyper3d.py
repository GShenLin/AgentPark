from __future__ import annotations

from typing import Any

from src.provider_limit_result import set_feature, set_value_features
from src.provider_limit_schema import REASONING_EFFORT_VALUES
from src.provider_limit_schema import ProbeResult


def test_hyper3d_limits(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    _ = config, timeout_seconds
    set_feature(result, "access", ProbeResult(True, "Configuration is present; generation endpoints are not probed to avoid creating billable jobs"))
    set_feature(result, "responses_api", ProbeResult(False, "Hyper3D provider is generation-only and has no Responses API"))
    set_feature(result, "web_search", ProbeResult(False, "Hyper3D provider is generation-only and has no web_search"))
    set_feature(result, "thinking", ProbeResult(False, "Hyper3D provider is generation-only and has no thinking"))
    set_value_features(
        result,
        "reasoning_effort",
        {effort: ProbeResult(False, "Hyper3D provider is generation-only and has no reasoning_effort") for effort in REASONING_EFFORT_VALUES},
    )
