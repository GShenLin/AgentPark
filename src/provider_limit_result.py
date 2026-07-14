from __future__ import annotations

from typing import Any

from src.provider_limit_schema import ProbeResult


def set_feature(result: dict[str, Any], feature_name: str, probe: ProbeResult) -> None:
    result.setdefault("features", {})[feature_name] = probe.to_payload()
    if probe.conclusively_unsupported:
        result.setdefault("unsupported", {})[feature_name] = str(probe.reason or "not supported")
    elif probe.inconclusive:
        result.setdefault("inconclusive", {})[feature_name] = str(probe.reason or probe.outcome)


def set_value_features(
    result: dict[str, Any],
    feature_name: str,
    probes: dict[str, ProbeResult],
) -> None:
    supported_values = [value for value, probe in probes.items() if probe.supported]
    result.setdefault("features", {})[feature_name] = {
        "supported": bool(supported_values),
        "outcome": aggregate_value_outcome(probes),
        "supported_values": supported_values,
        "values": {value: probe.to_payload() for value, probe in probes.items()},
    }
    unsupported_values = {
        value: probe.reason or "not supported"
        for value, probe in probes.items()
        if probe.conclusively_unsupported
    }
    if unsupported_values:
        result.setdefault("unsupported", {})[feature_name] = unsupported_values
    inconclusive_values = {
        value: probe.reason or probe.outcome
        for value, probe in probes.items()
        if probe.inconclusive
    }
    if inconclusive_values:
        result.setdefault("inconclusive", {})[feature_name] = inconclusive_values


def aggregate_value_outcome(probes: dict[str, ProbeResult]) -> str:
    if any(probe.supported for probe in probes.values()):
        return "supported"
    if any(probe.inconclusive for probe in probes.values()):
        return "not_tested"
    return "unsupported"
