from __future__ import annotations

import time

from . import anthropic_oauth, codex_oauth, kimi_oauth, xai_oauth
from .store import AuthStoreError, get_account, list_accounts, provider_auth_dir, remove_account, save_account, set_active_account


SUPPORTED_OAUTH_PROVIDERS = ("openai", "anthropic", "kimi", "xai")


class ProviderAuthorizationError(RuntimeError):
    pass


def provider_status(provider: str) -> dict:
    provider_id = str(provider or "").strip().lower()
    if provider_id == "openai":
        return {"provider": provider_id, "authModes": ["oauth", "api_key"], **codex_oauth.authorization_status()}
    accounts = list_accounts(provider_id)
    active = next((item for item in accounts if item["active"]), None)
    error = ""
    if active and active["kind"] == "oauth":
        try:
            credential = get_account(provider_id, active["id"])
            expires_at = int((credential.credential if credential else {}).get("expiresAt") or 0)
            if expires_at and expires_at <= int(time.time()) + 300:
                if provider_id == "kimi":
                    kimi_oauth.refresh_authorization(account_id=active["id"])
                elif provider_id == "xai":
                    xai_oauth.refresh_authorization(account_id=active["id"])
                elif provider_id == "anthropic":
                    anthropic_oauth.refresh_authorization(account_id=active["id"])
        except (
            AuthStoreError,
            anthropic_oauth.AnthropicOAuthError,
            kimi_oauth.KimiOAuthError,
            xai_oauth.XaiOAuthError,
        ) as exc:
            error = str(exc)
    return {
        "provider": provider_id,
        "authorized": active is not None and not error,
        "authModes": ["oauth", "api_key"] if provider_id in SUPPORTED_OAUTH_PROVIDERS else ["api_key"],
        "activeAccountId": str(active["id"] if active else ""),
        "accounts": accounts,
        "authPath": provider_auth_dir(provider_id),
        "error": error,
    }


def start_login(provider: str) -> dict:
    provider_id = str(provider or "").strip().lower()
    if provider_id == "openai":
        return codex_oauth.login_manager.start()
    if provider_id == "kimi":
        return kimi_oauth.login_manager.start()
    if provider_id == "xai":
        return xai_oauth.login_manager.start()
    if provider_id == "anthropic":
        return anthropic_oauth.login_manager.start()
    raise ProviderAuthorizationError(
        f"Provider '{provider_id}' uses API-key authorization; add an API-key account instead."
    )


def submit_login_code(provider: str, code: str) -> dict:
    provider_id = str(provider or "").strip().lower()
    if provider_id != "anthropic":
        raise ProviderAuthorizationError(f"Provider '{provider_id}' does not accept manual authorization codes.")
    try:
        anthropic_oauth.login_manager.submit_code(code)
    except anthropic_oauth.AnthropicOAuthError as exc:
        raise ProviderAuthorizationError(str(exc)) from exc
    return provider_status(provider_id)


def add_api_key_account(provider: str, *, api_key: str, alias: str = "", identity: str = "") -> dict:
    provider_id = str(provider or "").strip().lower()
    key = str(api_key or "").strip()
    if not key:
        raise ProviderAuthorizationError("apiKey must be a non-empty string.")
    stable_identity = str(identity or alias).strip()
    if not stable_identity:
        raise ProviderAuthorizationError("identity or alias is required for a multi-account API key.")
    save_account(
        provider_id,
        kind="api_key",
        credential={"apiKey": key},
        identity=stable_identity,
        alias=alias,
    )
    return provider_status(provider_id)


def activate_account(provider: str, account_id: str) -> dict:
    if not set_active_account(provider, account_id):
        raise ProviderAuthorizationError(f"Unknown account '{account_id}' for provider '{provider}'.")
    return provider_status(provider)


def delete_account(provider: str, account_id: str) -> dict:
    if not remove_account(provider, account_id):
        raise ProviderAuthorizationError(f"Unknown account '{account_id}' for provider '{provider}'.")
    return provider_status(provider)


__all__ = [
    "ProviderAuthorizationError",
    "SUPPORTED_OAUTH_PROVIDERS",
    "activate_account",
    "add_api_key_account",
    "delete_account",
    "provider_status",
    "start_login",
    "submit_login_code",
]
