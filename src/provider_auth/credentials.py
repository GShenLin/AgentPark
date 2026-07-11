from __future__ import annotations

from dataclasses import dataclass

from .codex_oauth import RESPONSES_BASE_URL, refresh_authorization


@dataclass(frozen=True)
class ProviderRequestCredentials:
    base_url: str
    headers: dict[str, str]


def resolve_provider_request_credentials(config: dict, *, force_refresh: bool = False) -> ProviderRequestCredentials:
    auth_mode = str(config.get("authMode") or "api_key").strip().lower()
    if auth_mode == "api_key":
        return ProviderRequestCredentials(
            base_url=str(config["baseUrl"]).rstrip("/"),
            headers={"Authorization": f"Bearer {config['apiKey']}"},
        )
    if auth_mode == "codex":
        credentials = refresh_authorization(force=force_refresh)
        return ProviderRequestCredentials(
            base_url=RESPONSES_BASE_URL,
            headers={
                "Authorization": f"Bearer {credentials.access_token}",
                "ChatGPT-Account-ID": credentials.account_id,
            },
        )
    raise ValueError(f"Unsupported provider authMode: {auth_mode}")
