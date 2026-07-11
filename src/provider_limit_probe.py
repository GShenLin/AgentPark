from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from typing import Any, Callable

from src.config_loader import ConfigLoader
from src.file_transaction import atomic_write_text
from src.provider_limit_claude import test_claude_limits
from src.provider_limit_channel import OPENAI_COMPATIBLE_PROVIDER_TYPES
from src.provider_limit_channel import openai_compatible_endpoint_url
from src.provider_limit_channel import provider_test_channels
from src.provider_limit_channel import resolve_provider_test_channel
from src.provider_limit_doubao import test_doubao_limits
from src.provider_limit_hyper3d import test_hyper3d_limits
from src.provider_limit_http import post_json_probe
from src.provider_limit_native_chat import test_gemini_limits
from src.provider_limit_native_chat import test_zhipu_limits
from src.provider_limit_openai import test_openai_limits
from src.provider_limit_schema import PROVIDER_LIMIT_SCHEMA_VERSION
from src.provider_limit_schema import ProbeResult
from src.provider_limit_schema import provider_limit_path
from src.provider_limit_static_contract import record_static_contract_limits

ProgressCallback = Callable[[dict[str, Any]], None]


def run_provider_limit_tests(
    *,
    timeout_seconds: float = 30.0,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    config = ConfigLoader().get_config()
    providers = config.get("providers")
    if not isinstance(providers, dict):
        providers = {}
    started = time.monotonic()
    output = {
        "schema_version": PROVIDER_LIMIT_SCHEMA_VERSION,
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_mode": "all_channels",
        "status": "running",
        "duration_ms": 0,
        "completed_providers": 0,
        "total_providers": 0,
        "current_provider_id": "",
        "providers": {},
    }
    provider_items = list(providers.items())
    total = len(provider_items)
    output["total_providers"] = total
    path = provider_limit_path()
    _write_provider_limit_snapshot(path, output, started=started)
    for index, (provider_id, provider) in enumerate(provider_items, start=1):
        safe_provider_id = str(provider_id)
        output["current_provider_id"] = safe_provider_id
        _write_provider_limit_snapshot(path, output, started=started)
        _emit_progress(
            progress_callback,
            provider_id=safe_provider_id,
            index=index,
            total=total,
            status="running",
        )
        try:
            output["providers"][safe_provider_id] = test_provider_all_channels(
                safe_provider_id,
                provider if isinstance(provider, dict) else {},
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            output["providers"][safe_provider_id] = _provider_probe_crash_payload(
                safe_provider_id,
                provider,
                exc,
            )
        output["completed_providers"] = index
        _write_provider_limit_snapshot(path, output, started=started)
        _emit_progress(
            progress_callback,
            provider_id=safe_provider_id,
            index=index,
            total=total,
            status="finished",
        )
    output["status"] = "finished"
    output["current_provider_id"] = ""
    _write_provider_limit_snapshot(path, output, started=started)
    output_with_path = {**output, "path": path}
    return output_with_path


def _write_provider_limit_snapshot(path: str, output: dict[str, Any], *, started: float) -> None:
    output["duration_ms"] = int((time.monotonic() - started) * 1000)
    atomic_write_text(path, json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

def _emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if not callable(callback):
        return
    try:
        callback(dict(payload))
    except Exception:
        return


def _provider_probe_crash_payload(
    provider_id: str,
    provider: object,
    exc: Exception,
) -> dict[str, Any]:
    config = provider if isinstance(provider, dict) else {}
    provider_type = str(config.get("type") or "")
    reason = f"{type(exc).__name__}: {exc}"
    channels = provider_test_channels(provider_type, config)
    channel_payloads = {
        channel: _channel_crash_payload(provider_id, provider_type, config, channel, reason)
        for channel in channels
    }
    primary_channel = resolve_provider_test_channel(provider_type, config, "configured")
    payload = {
        "provider_id": provider_id,
        "type": provider_type,
        "model": str(config.get("model") or ""),
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_channel": primary_channel,
        "accessible": False,
        "status": "unavailable",
        "access_error": reason,
        "features": {"access": {"supported": False, "reason": reason}},
        "unsupported": {"access": reason},
        "channels": channel_payloads,
    }
    if provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES:
        payload["test_endpoint"] = openai_compatible_endpoint_url(config, primary_channel)
    return payload


def _channel_crash_payload(
    provider_id: str,
    provider_type: str,
    config: dict[str, Any],
    channel: str,
    reason: str,
) -> dict[str, Any]:
    payload = {
        "provider_id": provider_id,
        "type": provider_type,
        "model": str(config.get("model") or ""),
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_channel": channel,
        "accessible": False,
        "status": "unavailable",
        "access_error": reason,
        "features": {"access": {"supported": False, "reason": reason}},
        "unsupported": {"access": reason},
    }
    if provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES:
        payload["test_endpoint"] = openai_compatible_endpoint_url(config, channel)
    return payload


def test_provider_all_channels(
    provider_id: str,
    provider: dict[str, Any],
    *,
    timeout_seconds: float,
) -> dict[str, Any]:
    provider_type = str(provider.get("type") or "").strip()
    channels = provider_test_channels(provider_type, provider)
    channel_results = {
        channel: test_provider_limits(
            provider_id,
            provider,
            timeout_seconds=timeout_seconds,
            test_channel=channel if provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES else "configured",
        )
        for channel in channels
    }
    primary_channel = resolve_provider_test_channel(provider_type, provider, "configured")
    primary = copy.deepcopy(channel_results[primary_channel])
    primary["channels"] = channel_results
    primary["accessible"] = any(bool(item.get("accessible")) for item in channel_results.values())
    primary["status"] = "ok" if primary["accessible"] else "unavailable"
    return primary

def test_provider_limits(
    provider_id: str,
    provider: dict[str, Any],
    *,
    timeout_seconds: float,
    test_channel: str = "configured",
) -> dict[str, Any]:
    config = copy.deepcopy(provider)
    provider_type = str(config.get("type") or "").strip()
    resolved_channel = resolve_provider_test_channel(provider_type, config, test_channel)
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "type": provider_type,
        "model": str(config.get("model") or ""),
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "test_channel": resolved_channel,
        "accessible": False,
        "features": {},
        "unsupported": {},
    }
    if provider_type in OPENAI_COMPATIBLE_PROVIDER_TYPES:
        result["test_endpoint"] = openai_compatible_endpoint_url(config, resolved_channel)

    validation_error = _validate_common_config(config, provider_type)
    if validation_error:
        result["status"] = "unavailable"
        result["access_error"] = validation_error
        _record_unsupported(result, "access", validation_error)
        record_static_contract_limits(result, provider_type, skip_access=True)
        return result

    tester = _tester_for_type(provider_type)
    if tester is None:
        reason = f"provider type '{provider_type or '<empty>'}' has no provider-limit probe"
        result["status"] = "unavailable"
        result["access_error"] = reason
        _record_unsupported(result, "access", reason)
        record_static_contract_limits(result, provider_type, skip_access=True)
        return result

    tester(
        result,
        config,
        timeout_seconds=max(1.0, float(timeout_seconds or 30.0)),
        test_channel=resolved_channel,
    )
    result["accessible"] = bool((result.get("features") or {}).get("access", {}).get("supported"))
    result["status"] = "ok" if result["accessible"] else "unavailable"
    return result

def _validate_common_config(config: dict[str, Any], provider_type: str) -> str:
    if not provider_type:
        return "provider.type is required"
    if not str(config.get("apiKey") or "").strip():
        return "provider.apiKey is required"
    if provider_type != "hyper3d" and not str(config.get("model") or "").strip():
        return "provider.model is required"
    if not str(config.get("baseUrl") or "").strip():
        return "provider.baseUrl is required"
    return ""

def _tester_for_type(provider_type: str):
    return {
        "openai": _test_openai_compatible,
        "claude": _test_claude,
        "doubao": _test_doubao,
        "zhipu": _test_zhipu,
        "gemini": _test_gemini,
        "hyper3d": _test_hyper3d,
    }.get(provider_type)

def _test_openai_compatible(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    timeout_seconds: float,
    test_channel: str,
) -> None:
    test_openai_limits(
        result,
        config,
        test_channel=test_channel,
        post_json_probe=lambda url, headers, payload: post_json_probe(
            url,
            headers,
            payload,
            timeout_seconds=timeout_seconds,
        ),
    )

def _test_doubao(
    result: dict[str, Any],
    config: dict[str, Any],
    *,
    timeout_seconds: float,
    test_channel: str,
) -> None:
    test_doubao_limits(
        result,
        config,
        test_channel=test_channel,
        timeout_seconds=timeout_seconds,
        post_json_probe=lambda url, headers, payload: post_json_probe(
            url,
            headers,
            payload,
            timeout_seconds=timeout_seconds,
        ),
    )


def _test_claude(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float, test_channel: str) -> None:
    _ = test_channel
    test_claude_limits(
        result,
        config,
        timeout_seconds=timeout_seconds,
        post_json_probe=lambda url, headers, payload: post_json_probe(
            url,
            headers,
            payload,
            timeout_seconds=timeout_seconds,
        ),
    )


def _test_zhipu(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float, test_channel: str) -> None:
    _ = test_channel
    test_zhipu_limits(
        result,
        config,
        post_json_probe=lambda url, headers, payload: post_json_probe(
            url, headers, payload, timeout_seconds=timeout_seconds
        ),
    )

def _test_gemini(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float, test_channel: str) -> None:
    _ = test_channel
    test_gemini_limits(
        result,
        config,
        post_json_probe=lambda url, headers, payload: post_json_probe(
            url, headers, payload, timeout_seconds=timeout_seconds
        ),
    )

def _test_hyper3d(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float, test_channel: str) -> None:
    _ = test_channel
    test_hyper3d_limits(result, config, timeout_seconds=timeout_seconds)


def _set_feature(result: dict[str, Any], feature_name: str, probe: ProbeResult) -> None:
    features = result.setdefault("features", {})
    features[feature_name] = probe.to_payload()
    if not probe.supported:
        _record_unsupported(result, feature_name, probe.reason)


def _set_value_features(result: dict[str, Any], feature_name: str, probes: dict[str, ProbeResult]) -> None:
    supported_values = [value for value, probe in probes.items() if probe.supported]
    values_payload = {value: probe.to_payload() for value, probe in probes.items()}
    result.setdefault("features", {})[feature_name] = {
        "supported": bool(supported_values),
        "supported_values": supported_values,
        "values": values_payload,
    }
    unsupported_values = {
        value: probe.reason or "not supported"
        for value, probe in probes.items()
        if not probe.supported
    }
    if unsupported_values:
        result.setdefault("unsupported", {})[feature_name] = unsupported_values


def _record_unsupported(result: dict[str, Any], name: str, reason: str) -> None:
    result.setdefault("unsupported", {})[name] = str(reason or "not supported")


__all__ = ["run_provider_limit_tests", "test_provider_all_channels", "test_provider_limits"]
