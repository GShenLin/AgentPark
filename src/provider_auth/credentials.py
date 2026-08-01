from __future__ import annotations

from dataclasses import dataclass

from .codex_oauth import RESPONSES_BASE_URL, refresh_authorization as refresh_openai
from .kimi_oauth import refresh_authorization as refresh_kimi
from .xai_oauth import refresh_authorization as refresh_xai
from .anthropic_oauth import refresh_authorization as refresh_anthropic
from .store import get_account


CODEX_ORIGINATOR = "codex_cli_rs"
CODEX_USER_AGENT = "codex_cli_rs/0.0.0 (Windows; x86_64) AgentPark"


@dataclass(frozen=True)
class ProviderRequestCredentials:
    base_url: str
    headers: dict[str, str]


def resolve_provider_request_credentials(config: dict, *, force_refresh: bool = False) -> ProviderRequestCredentials:
    auth_mode = str(config.get("authMode") or "api_key").strip().lower()
    provider_id = str(
        config.get("authProvider")
        or config.get("type")
        or ("openai" if auth_mode == "codex" else "")
    ).strip().lower()
    account_id = str(config.get("authAccountId") or "").strip() or None
    if auth_mode == "api_key":
        api_key = resolve_provider_api_key(config)
        if provider_id in {"anthropic", "claude"}:
            return ProviderRequestCredentials(
                base_url=str(config["baseUrl"]).rstrip("/"),
                headers={
                    "x-api-key": api_key,
                    "anthropic-version": str(config.get("anthropicVersion") or "2023-06-01"),
                },
            )
        return ProviderRequestCredentials(
            base_url=str(config["baseUrl"]).rstrip("/"),
            headers={"Authorization": f"Bearer {api_key}"},
        )
    if auth_mode in {"codex", "oauth"} and provider_id == "openai":
        credentials = refresh_openai(force=force_refresh, account_id=account_id)
        return ProviderRequestCredentials(
            base_url=RESPONSES_BASE_URL,
            headers={
                "Authorization": f"Bearer {credentials.access_token}",
                "ChatGPT-Account-ID": credentials.account_id,
                "originator": CODEX_ORIGINATOR,
                "User-Agent": CODEX_USER_AGENT,
            },
        )
    if auth_mode == "oauth" and provider_id == "kimi":
        credentials = refresh_kimi(force=force_refresh, account_id=account_id)
        return ProviderRequestCredentials(
            base_url=str(config["baseUrl"]).rstrip("/"),
            headers={"Authorization": f"Bearer {credentials['accessToken']}"},
        )
    if auth_mode == "oauth" and provider_id in {"xai", "grok"}:
        credentials = refresh_xai(force=force_refresh, account_id=account_id)
        return ProviderRequestCredentials(
            base_url=str(config["baseUrl"]).rstrip("/"),
            headers={"Authorization": f"Bearer {credentials['accessToken']}"},
        )
    if auth_mode == "oauth" and provider_id in {"anthropic", "claude"}:
        credentials = refresh_anthropic(force=force_refresh, account_id=account_id)
        return ProviderRequestCredentials(
            base_url=str(config["baseUrl"]).rstrip("/"),
            headers={
                "Authorization": f"Bearer {credentials['accessToken']}",
                "anthropic-version": str(config.get("anthropicVersion") or "2023-06-01"),
            },
        )
    raise ValueError(f"Unsupported provider authMode: {auth_mode}")


def resolve_provider_api_key(config: dict) -> str:
    auth_mode = str(config.get("authMode") or "api_key").strip().lower()
    if auth_mode != "api_key":
        raise ValueError(f"Provider authMode {auth_mode!r} does not use an API key.")
    provider_id = str(config.get("authProvider") or config.get("type") or "").strip().lower()
    account_id = str(config.get("authAccountId") or "").strip() or None
    stored = get_account(provider_id, account_id) if provider_id else None
    api_key = str(
        stored.credential.get("apiKey")
        if stored and stored.kind == "api_key"
        else config.get("apiKey") or ""
    )
    if not api_key:
        raise ValueError(f"Provider '{provider_id or 'unknown'}' has no active API-key account.")
    return api_key


__all__ = [
    "ProviderRequestCredentials",
    "resolve_provider_api_key",
    "resolve_provider_request_credentials",
]
