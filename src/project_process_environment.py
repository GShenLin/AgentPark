from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit

from src.workspace_settings import load_workspace_settings
from src.runtime_environment import initialize_runtime_environment


DEFAULT_NO_PROXY = "localhost,127.0.0.1,::1"


def read_project_proxy_settings(
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    settings = load_workspace_settings() if payload is None else payload
    if not isinstance(settings, dict):
        raise ValueError("config/config.json must contain a top-level object.")

    network = settings.get("network")
    if network is None:
        network = {}
    if not isinstance(network, dict):
        raise ValueError("config/config.json field 'network' must be an object.")

    http_proxy = _text_field(network, "httpProxy")
    no_proxy = _text_field(network, "noProxy")
    if http_proxy:
        _validate_proxy_url(http_proxy)
    return {
        "http_proxy": http_proxy,
        "no_proxy": no_proxy,
    }


def apply_project_process_environment(
    payload: dict[str, Any] | None = None,
) -> dict[str, str]:
    proxy = read_project_proxy_settings(payload)
    initialize_runtime_environment()
    http_proxy = proxy["http_proxy"]
    no_proxy = proxy["no_proxy"]

    if http_proxy:
        os.environ["HTTP_PROXY"] = http_proxy
        os.environ["HTTPS_PROXY"] = http_proxy
        os.environ["http_proxy"] = http_proxy
        os.environ["https_proxy"] = http_proxy
    if no_proxy:
        os.environ["NO_PROXY"] = no_proxy
        os.environ["no_proxy"] = no_proxy
    elif http_proxy:
        os.environ["NO_PROXY"] = DEFAULT_NO_PROXY
        os.environ["no_proxy"] = DEFAULT_NO_PROXY

    return {
        "HTTP_PROXY": str(os.environ.get("HTTP_PROXY") or ""),
        "HTTPS_PROXY": str(os.environ.get("HTTPS_PROXY") or ""),
        "NO_PROXY": str(os.environ.get("NO_PROXY") or ""),
    }


def _text_field(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValueError(f"config/config.json field 'network.{key}' must be a string.")
    text = value.strip()
    if any(char in text for char in ("\0", "\r", "\n")):
        raise ValueError(f"config/config.json field 'network.{key}' contains invalid characters.")
    return text


def _validate_proxy_url(value: str) -> None:
    parsed = urlsplit(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(
            "config/config.json field 'network.httpProxy' must be an absolute http:// or https:// URL."
        )


__all__ = [
    "DEFAULT_NO_PROXY",
    "apply_project_process_environment",
    "read_project_proxy_settings",
]
