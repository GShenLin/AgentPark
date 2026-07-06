from __future__ import annotations

from typing import Any

from src.provider_limit_schema import REASONING_EFFORT_VALUES
from src.provider_limit_schema import ProbeResult


def test_hyper3d_limits(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    _ = config, timeout_seconds
    _set_feature(result, "access", ProbeResult(True, "Configuration is present; generation endpoints are not probed to avoid creating billable jobs"))
    _set_feature(result, "responses_api", ProbeResult(False, "Hyper3D provider is generation-only and has no Responses API"))
    _set_feature(result, "web_search", ProbeResult(False, "Hyper3D provider is generation-only and has no web_search"))
    _set_feature(result, "thinking", ProbeResult(False, "Hyper3D provider is generation-only and has no thinking"))
    _set_value_features(
        result,
        "reasoning_effort",
        {effort: ProbeResult(False, "Hyper3D provider is generation-only and has no reasoning_effort") for effort in REASONING_EFFORT_VALUES},
    )


def _set_feature(result: dict[str, Any], feature_name: str, probe: ProbeResult) -> None:
    features = result.setdefault("features", {})
    features[feature_name] = probe.to_payload()
    if not probe.supported:
        result.setdefault("unsupported", {})[feature_name] = str(probe.reason or "not supported")


def _set_value_features(result: dict[str, Any], feature_name: str, probes: dict[str, ProbeResult]) -> None:
    supported_values = [value for value, probe in probes.items() if probe.supported]
    result.setdefault("features", {})[feature_name] = {
        "supported": bool(supported_values),
        "supported_values": supported_values,
        "values": {value: probe.to_payload() for value, probe in probes.items()},
    }
    result.setdefault("unsupported", {})[feature_name] = {
        value: probe.reason or "not supported" for value, probe in probes.items() if not probe.supported
    }
