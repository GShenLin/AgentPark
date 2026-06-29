from __future__ import annotations

import copy
import json
import time
from datetime import datetime
from typing import Any, Callable

from src.config_loader import ConfigLoader
from src.file_transaction import atomic_write_text
from src.providers.curl_transport import CurlHttpTransport
from src.providers.curl_transport import CurlTransportError
from src.provider_limit_schema import PROVIDER_LIMIT_SCHEMA_VERSION
from src.provider_limit_schema import REASONING_EFFORT_VALUES
from src.provider_limit_schema import THINKING_VALUES
from src.provider_limit_schema import ProbeResult
from src.provider_limit_schema import provider_limit_path

ProgressCallback = Callable[[dict[str, Any]], None]


class _ProviderLimitCurl(CurlHttpTransport):
    pass

_CURL = _ProviderLimitCurl()


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
            output["providers"][safe_provider_id] = test_provider_limits(
                safe_provider_id,
                provider if isinstance(provider, dict) else {},
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            output["providers"][safe_provider_id] = _provider_probe_crash_payload(safe_provider_id, provider, exc)
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


def _provider_probe_crash_payload(provider_id: str, provider: object, exc: Exception) -> dict[str, Any]:
    config = provider if isinstance(provider, dict) else {}
    reason = f"{type(exc).__name__}: {exc}"
    return {
        "provider_id": provider_id,
        "type": str(config.get("type") or ""),
        "model": str(config.get("model") or ""),
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "accessible": False,
        "status": "unavailable",
        "access_error": reason,
        "features": {"access": {"supported": False, "reason": reason}},
        "unsupported": {"access": reason},
    }

def test_provider_limits(provider_id: str, provider: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    config = copy.deepcopy(provider)
    provider_type = str(config.get("type") or "").strip().lower()
    result: dict[str, Any] = {
        "provider_id": provider_id,
        "type": provider_type,
        "model": str(config.get("model") or ""),
        "tested_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "accessible": False,
        "features": {},
        "unsupported": {},
    }

    validation_error = _validate_common_config(config, provider_type)
    if validation_error:
        result["status"] = "unavailable"
        result["access_error"] = validation_error
        _record_unsupported(result, "access", validation_error)
        _record_static_contract_limits(result, provider_type, skip_access=True)
        return result

    tester = _tester_for_type(provider_type)
    if tester is None:
        reason = f"provider type '{provider_type or '<empty>'}' has no provider-limit probe"
        result["status"] = "unavailable"
        result["access_error"] = reason
        _record_unsupported(result, "access", reason)
        _record_static_contract_limits(result, provider_type, skip_access=True)
        return result

    tester(result, config, timeout_seconds=max(1.0, float(timeout_seconds or 30.0)))
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
        "doubao": _test_doubao,
        "zhipu": _test_zhipu,
        "gemini": _test_gemini,
        "hyper3d": _test_hyper3d,
    }.get(provider_type)

def _test_openai_compatible(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    access = _probe_chat_completions(config, {}, timeout_seconds=timeout_seconds)
    _set_feature(result, "access", access)
    responses = _probe_responses(config, {}, timeout_seconds=timeout_seconds)
    _set_feature(result, "responses_api", responses)
    _set_feature(result, "web_search", _probe_responses(config, _web_search_payload(config), timeout_seconds=timeout_seconds))
    _set_feature(result, "thinking", ProbeResult(False, "OpenAI provider contract does not send thinking"))
    _set_value_features(
        result,
        "reasoning_effort",
        {
            effort: _probe_responses(config, {"reasoning": {"effort": effort}}, timeout_seconds=timeout_seconds)
            for effort in REASONING_EFFORT_VALUES
        },
    )

def _test_doubao(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    access = _probe_chat_completions(config, {}, timeout_seconds=timeout_seconds)
    _set_feature(result, "access", access)
    responses = _probe_responses(config, {}, timeout_seconds=timeout_seconds)
    _set_feature(result, "responses_api", responses)
    _set_feature(result, "web_search", _probe_responses(config, _doubao_web_search_payload(config), timeout_seconds=timeout_seconds))
    _set_value_features(
        result,
        "thinking",
        {
            mode: _probe_chat_completions(config, {"thinking": {"type": mode}}, timeout_seconds=timeout_seconds)
            for mode in THINKING_VALUES
        },
    )
    _set_value_features(
        result,
        "reasoning_effort",
        {effort: ProbeResult(False, "Doubao provider contract does not send reasoning_effort") for effort in REASONING_EFFORT_VALUES},
    )


def _test_zhipu(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    access = _probe_chat_completions(config, {}, timeout_seconds=timeout_seconds)
    _set_feature(result, "access", access)
    _set_feature(result, "responses_api", ProbeResult(False, "Zhipu provider contract uses chat/completions, not Responses API"))
    _set_feature(result, "web_search", ProbeResult(False, "Zhipu provider contract does not send web_search"))
    _set_value_features(
        result,
        "thinking",
        {
            "enabled": _probe_chat_completions(config, {"thinking": {"type": "enabled"}}, timeout_seconds=timeout_seconds),
            "disabled": _probe_chat_completions(config, {"thinking": {"type": "disabled"}}, timeout_seconds=timeout_seconds),
            "auto": ProbeResult(False, "Zhipu thinking supports enabled/disabled only"),
        },
    )
    _set_value_features(
        result,
        "reasoning_effort",
        {
            effort: _probe_chat_completions(config, {"reasoning_effort": effort}, timeout_seconds=timeout_seconds)
            for effort in REASONING_EFFORT_VALUES
        },
    )

def _test_gemini(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    _set_feature(result, "access", _probe_gemini_generate_content(config, timeout_seconds=timeout_seconds))
    _set_feature(result, "responses_api", ProbeResult(False, "Gemini provider contract uses generateContent, not Responses API"))
    _set_feature(result, "web_search", ProbeResult(False, "Gemini provider contract does not send web_search"))
    _set_feature(result, "thinking", ProbeResult(False, "Gemini provider contract does not send thinking"))
    _set_value_features(
        result,
        "reasoning_effort",
        {effort: ProbeResult(False, "Gemini provider contract does not send reasoning_effort") for effort in REASONING_EFFORT_VALUES},
    )

def _test_hyper3d(result: dict[str, Any], config: dict[str, Any], *, timeout_seconds: float) -> None:
    _ = timeout_seconds
    _set_feature(result, "access", ProbeResult(True, "Configuration is present; generation endpoints are not probed to avoid creating billable jobs"))
    _set_feature(result, "responses_api", ProbeResult(False, "Hyper3D provider is generation-only and has no Responses API"))
    _set_feature(result, "web_search", ProbeResult(False, "Hyper3D provider is generation-only and has no web_search"))
    _set_feature(result, "thinking", ProbeResult(False, "Hyper3D provider is generation-only and has no thinking"))
    _set_value_features(
        result,
        "reasoning_effort",
        {effort: ProbeResult(False, "Hyper3D provider is generation-only and has no reasoning_effort") for effort in REASONING_EFFORT_VALUES},
    )


def _probe_chat_completions(config: dict[str, Any], extra_payload: dict[str, Any], *, timeout_seconds: float) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "messages": [{"role": "user", "content": "Reply exactly OK."}],
        **extra_payload,
    }
    url = f"{_base_url(config)}/chat/completions"
    headers = _bearer_headers(config)
    return _post_json_probe(url, headers, payload, timeout_seconds=timeout_seconds)


def _probe_responses(config: dict[str, Any], extra_payload: dict[str, Any], *, timeout_seconds: float) -> ProbeResult:
    payload = {
        "model": str(config.get("model") or ""),
        "input": [{"role": "user", "content": [{"type": "input_text", "text": "Reply exactly OK."}]}],
        **extra_payload,
    }
    url = f"{_base_url(config)}/responses"
    headers = _bearer_headers(config)
    return _post_json_probe(url, headers, payload, timeout_seconds=timeout_seconds)


def _probe_gemini_generate_content(config: dict[str, Any], *, timeout_seconds: float) -> ProbeResult:
    payload = {"contents": [{"role": "user", "parts": [{"text": "Reply exactly OK."}]}]}
    url = f"{_base_url(config)}/models/{str(config.get('model') or '').strip()}:generateContent"
    headers = {
        "Content-Type": "application/json",
        "x-goog-api-key": str(config.get("apiKey") or ""),
    }
    return _post_json_probe(url, headers, payload, timeout_seconds=timeout_seconds)


def _post_json_probe(url: str, headers: dict[str, str], payload: dict[str, Any], *, timeout_seconds: float) -> ProbeResult:
    payload_json = json.dumps(payload, ensure_ascii=False)
    try:
        response = _CURL._curl_post_once_raw(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_seconds,
            marker="__PROVIDER_LIMIT_HTTP_CODE__:",
        )
        if response.status_code < 200 or response.status_code >= 300:
            return ProbeResult(
                False,
                _sanitize_error(f"HTTP {response.status_code}: {response.body}", config_api_key=headers),
                status_code=response.status_code,
            )
        try:
            _ = json.loads(response.body) if response.body.strip() else {}
        except Exception as exc:
            return ProbeResult(
                False,
                _sanitize_error(f"Invalid JSON response: {exc}; body={response.body[:500]}", config_api_key=headers),
                status_code=response.status_code,
            )
        return ProbeResult(True, status_code=response.status_code)
    except CurlTransportError as exc:
        return ProbeResult(False, _sanitize_error(f"curl: {exc}", config_api_key=headers))
    except Exception as exc:
        return ProbeResult(False, _sanitize_error(f"{type(exc).__name__}: {exc}", config_api_key=headers))


def _web_search_payload(config: dict[str, Any]) -> dict[str, Any]:
    tool_type = str(config.get("webSearchToolType", config.get("web_search_tool_type", "web_search")) or "").strip()
    return {"tools": [{"type": tool_type or "web_search"}]}


def _doubao_web_search_payload(config: dict[str, Any]) -> dict[str, Any]:
    tool: dict[str, Any] = {"type": "web_search"}
    for source_key, target_key in (
        ("webSearchMaxKeyword", "max_keyword"),
        ("webSearchLimit", "limit"),
    ):
        value = config.get(source_key)
        if isinstance(value, int) and value > 0:
            tool[target_key] = value
    sources = config.get("webSearchSources")
    if isinstance(sources, list) and sources:
        tool["sources"] = [str(item) for item in sources if str(item or "").strip()]
    return {"tools": [tool]}


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


def _record_static_contract_limits(result: dict[str, Any], provider_type: str, *, skip_access: bool) -> None:
    if not skip_access:
        return
    if provider_type not in {"openai", "doubao", "zhipu", "gemini", "hyper3d"}:
        return
    result.setdefault("features", {})
    result.setdefault("unsupported", {})
    for feature in ("responses_api", "web_search", "thinking", "reasoning_effort"):
        if feature not in result["unsupported"]:
            result["unsupported"][feature] = "not tested because provider is not accessible"


def _base_url(config: dict[str, Any]) -> str:
    return str(config.get("baseUrl") or "").strip().rstrip("/")


def _bearer_headers(config: dict[str, Any]) -> dict[str, str]:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {str(config.get('apiKey') or '')}",
    }


def _sanitize_error(text: str, *, config_api_key: dict[str, str]) -> str:
    output = str(text or "").strip()
    auth = str((config_api_key or {}).get("Authorization") or "")
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
        if token:
            output = output.replace(token, "<redacted>")
    api_key = str((config_api_key or {}).get("x-goog-api-key") or "")
    if api_key:
        output = output.replace(api_key, "<redacted>")
    return output[:1200]
