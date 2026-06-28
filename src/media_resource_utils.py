from __future__ import annotations

import json
import os
from urllib.parse import urlparse

from src.config_loader import ConfigLoader


def normalize_public_base_url(value: object) -> str:
    text = str(value or "").strip()
    return text.rstrip("/") if text else ""


def resolve_public_base_url(explicit: object, provider_id: object = "") -> str:
    direct = normalize_public_base_url(explicit)
    if direct:
        return direct

    env_value = normalize_public_base_url(os.environ.get("AITOOLS_PUBLIC_BASE_URL"))
    if env_value:
        return env_value

    try:
        full_config = ConfigLoader().get_config()
    except Exception:
        full_config = {}
    if isinstance(full_config, dict):
        top_level = normalize_public_base_url(
            full_config.get("publicBaseUrl") or full_config.get("public_base_url")
        )
        if top_level:
            return top_level

    try:
        provider_config = ConfigLoader().get_provider_config(provider_id)
    except Exception:
        provider_config = {}
    if isinstance(provider_config, dict):
        provider_level = normalize_public_base_url(
            provider_config.get("publicBaseUrl") or provider_config.get("public_base_url")
        )
        if provider_level:
            return provider_level

    return ""


def parse_resource_list(value: object) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    text = str(value or "").strip()
    if not text:
        return []
    if text.startswith("["):
        try:
            parsed = json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]
    return [line.strip() for line in text.splitlines() if line.strip()]


def uri_extension(uri: object) -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    parsed = urlparse(raw)
    path = parsed.path if parsed.scheme else raw
    return os.path.splitext(path.lower())[1]


def uri_has_extension(uri: object, extensions: set[str]) -> bool:
    return uri_extension(uri) in extensions


def dedupe_preserve_order(items: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item or "").strip()
        if not text:
            continue
        key = text.lower()
        if key in seen:
            continue
        seen.add(key)
        output.append(text)
    return output
