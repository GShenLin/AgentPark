from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Any, Callable

from src.config_loader import ConfigLoader
from src.file_transaction import atomic_write_text
from src.provider_limit_channel import resolve_provider_test_channel
from src.providers.curl_transport import CurlHttpTransport, CurlTransportError
from src.provider_limit_schema import PROVIDER_LIMIT_SCHEMA_VERSION
from src.provider_limit_schema import provider_limit_path
from src.provider_limit_schema import read_provider_limit_file


ProgressCallback = Callable[[dict[str, Any]], None]


class _ProviderModelCurl(CurlHttpTransport):
    pass


_CURL = _ProviderModelCurl()


def run_provider_model_discovery(
    *,
    timeout_seconds: float = 30.0,
    progress_callback: ProgressCallback | None = None,
) -> dict[str, Any]:
    config = ConfigLoader().get_config()
    providers = config.get("providers") if isinstance(config.get("providers"), dict) else {}
    output = _load_existing_provider_limit()
    started = time.monotonic()
    provider_items = list(providers.items())
    total = len(provider_items)
    output.update(
        {
            "schema_version": PROVIDER_LIMIT_SCHEMA_VERSION,
            "test_mode": "all_channels",
            "model_refresh_status": "running",
            "model_refresh_started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "model_refresh_completed_providers": 0,
            "model_refresh_total_providers": total,
            "model_refresh_current_provider_id": "",
        }
    )
    path = provider_limit_path()
    _write_snapshot(path, output, started=started)

    for index, (provider_id, provider) in enumerate(provider_items, start=1):
        safe_provider_id = str(provider_id)
        output["model_refresh_current_provider_id"] = safe_provider_id
        _write_snapshot(path, output, started=started)
        _emit_progress(progress_callback, provider_id=safe_provider_id, index=index, total=total, status="running")
        result = discover_provider_models(
            provider if isinstance(provider, dict) else {},
            timeout_seconds=max(1.0, float(timeout_seconds or 30.0)),
        )
        _merge_model_result(output, safe_provider_id, provider if isinstance(provider, dict) else {}, result)
        output["model_refresh_completed_providers"] = index
        _write_snapshot(path, output, started=started)
        _emit_progress(progress_callback, provider_id=safe_provider_id, index=index, total=total, status="finished")

    output["model_refresh_status"] = "finished"
    output["model_refresh_finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    output["model_refresh_current_provider_id"] = ""
    _write_snapshot(path, output, started=started)
    return {**output, "path": path}


def discover_provider_models(provider: dict[str, Any], *, timeout_seconds: float) -> dict[str, Any]:
    provider_type = str(provider.get("type") or "").strip()
    tested_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    validation_error = _validate_model_config(provider, provider_type)
    if validation_error:
        return _model_result(False, tested_at=tested_at, reason=validation_error)
    endpoint = _models_endpoint(provider, provider_type)
    if not endpoint:
        return _model_result(False, tested_at=tested_at, reason=f"provider type '{provider_type}' has no model discovery endpoint")
    headers = _model_headers(provider, provider_type)
    try:
        response = _CURL._curl_get_text_once_raw(
            url=endpoint,
            headers=headers,
            timeout_sec=timeout_seconds,
            marker="__PROVIDER_MODELS_HTTP_CODE__:",
        )
        if response.status_code < 200 or response.status_code >= 300:
            return _model_result(
                False,
                tested_at=tested_at,
                endpoint=endpoint,
                reason=_sanitize_error(f"HTTP {response.status_code}: {response.body}", headers),
                status_code=response.status_code,
            )
        payload = json.loads(response.body) if response.body.strip() else {}
        model_ids = _extract_model_ids(payload, provider_type)
        return _model_result(True, tested_at=tested_at, endpoint=endpoint, model_ids=model_ids, status_code=response.status_code)
    except CurlTransportError as exc:
        return _model_result(False, tested_at=tested_at, endpoint=endpoint, reason=_sanitize_error(f"curl: {exc}", headers))
    except Exception as exc:
        return _model_result(False, tested_at=tested_at, endpoint=endpoint, reason=_sanitize_error(f"{type(exc).__name__}: {exc}", headers))


def _load_existing_provider_limit() -> dict[str, Any]:
    try:
        payload = read_provider_limit_file()
    except Exception:
        payload = {"schema_version": PROVIDER_LIMIT_SCHEMA_VERSION, "generated_at": "", "providers": {}}
    payload.pop("path", None)
    if not isinstance(payload.get("providers"), dict):
        payload["providers"] = {}
    return payload


def _merge_model_result(output: dict[str, Any], provider_id: str, provider: dict[str, Any], result: dict[str, Any]) -> None:
    providers = output.setdefault("providers", {})
    entry = providers.get(provider_id) if isinstance(providers.get(provider_id), dict) else {}
    entry.update(
        {
            "provider_id": provider_id,
            "type": str(provider.get("type") or entry.get("type") or "").strip(),
            "model": str(provider.get("model") or entry.get("model") or ""),
            "available_model_ids": result["model_ids"],
            "model_discovery": {
                "supported": result["supported"],
                "tested_at": result["tested_at"],
                **({"endpoint": result["endpoint"]} if result.get("endpoint") else {}),
                **({"reason": result["reason"]} if result.get("reason") else {}),
                **({"status_code": result["status_code"]} if result.get("status_code") else {}),
            },
        }
    )
    entry["test_channel"] = _default_provider_test_channel(provider)
    entry.setdefault("features", {})
    entry.setdefault("unsupported", {})
    if result["supported"]:
        entry["accessible"] = True
        entry["status"] = "ok"
    else:
        entry.setdefault("accessible", False)
        entry.setdefault("status", "unavailable")
    providers[provider_id] = entry


def _default_provider_test_channel(provider: dict[str, Any]) -> str:
    return resolve_provider_test_channel(str(provider.get("type") or ""), provider, "configured")


def _model_result(
    supported: bool,
    *,
    tested_at: str,
    endpoint: str = "",
    model_ids: list[str] | None = None,
    reason: str = "",
    status_code: int = 0,
) -> dict[str, Any]:
    return {
        "supported": bool(supported),
        "tested_at": tested_at,
        "endpoint": endpoint,
        "model_ids": list(model_ids or []),
        "reason": str(reason or ""),
        "status_code": int(status_code or 0),
    }


def _extract_model_ids(payload: Any, provider_type: str) -> list[str]:
    if not isinstance(payload, dict):
        raise ValueError("models response must be a JSON object")
    items = payload.get("models") if provider_type == "gemini" else payload.get("data")
    if items is None:
        items = payload.get("data") if provider_type == "gemini" else payload.get("models")
    if not isinstance(items, list):
        raise ValueError("models response must contain a list field")
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        model_id = _model_id_from_item(item, provider_type)
        if model_id and model_id not in seen:
            seen.add(model_id)
            output.append(model_id)
    return output


def _model_id_from_item(item: Any, provider_type: str) -> str:
    if isinstance(item, str):
        value = item
    elif isinstance(item, dict):
        value = str(item.get("id") or item.get("name") or "").strip()
    else:
        value = ""
    if provider_type == "gemini" and value.startswith("models/"):
        value = value.split("/", 1)[1]
    return value.strip()


def _models_endpoint(provider: dict[str, Any], provider_type: str) -> str:
    if provider_type in {"openai", "deepseek", "claude", "doubao", "zhipu", "gemini"}:
        return f"{_base_url(provider)}/models"
    return ""


def _model_headers(provider: dict[str, Any], provider_type: str) -> dict[str, str]:
    if provider_type == "gemini":
        return {"x-goog-api-key": str(provider.get("apiKey") or "")}
    if provider_type == "claude":
        return {
            "x-api-key": str(provider.get("apiKey") or ""),
            "anthropic-version": str(provider.get("anthropicVersion") or "2023-06-01"),
        }
    return {"Authorization": f"Bearer {str(provider.get('apiKey') or '')}"}


def _validate_model_config(provider: dict[str, Any], provider_type: str) -> str:
    if not provider_type:
        return "provider.type is required"
    if not str(provider.get("apiKey") or "").strip():
        return "provider.apiKey is required"
    if not str(provider.get("baseUrl") or "").strip():
        return "provider.baseUrl is required"
    return ""


def _base_url(provider: dict[str, Any]) -> str:
    return str(provider.get("baseUrl") or "").strip().rstrip("/")


def _write_snapshot(path: str, output: dict[str, Any], *, started: float) -> None:
    output["model_refresh_duration_ms"] = int((time.monotonic() - started) * 1000)
    atomic_write_text(path, json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _emit_progress(callback: ProgressCallback | None, **payload: Any) -> None:
    if callable(callback):
        callback(dict(payload))


def _sanitize_error(text: str, headers: dict[str, str]) -> str:
    output = str(text or "").strip()
    auth = str((headers or {}).get("Authorization") or "")
    if auth.startswith("Bearer "):
        token = auth.removeprefix("Bearer ").strip()
        if token:
            output = output.replace(token, "<redacted>")
    api_key = str((headers or {}).get("x-goog-api-key") or "")
    if api_key:
        output = output.replace(api_key, "<redacted>")
    anthropic_key = str((headers or {}).get("x-api-key") or "")
    if anthropic_key:
        output = output.replace(anthropic_key, "<redacted>")
    return output[:1200]
