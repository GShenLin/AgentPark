from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src import workspace_settings
from src.provider_auth.codex_oauth import CodexOAuthError, authorization_status, login_manager
from src.provider_auth.codex_credential_sync import sync_local_codex_credentials
from src.provider_auth.store import AuthStoreError
from src.provider_auth.service import (
    ProviderAuthorizationError,
    activate_account,
    add_api_key_account,
    delete_account,
    provider_status,
    start_login,
    submit_login_code,
)
from src.provider_api_key_store import (
    ApiKeyAliasValidationError,
    add_api_key_alias,
    api_key_store_path,
    list_api_key_names,
)

from .domain_base import DomainBase


class CodexCredentialSyncRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    accountId: str | None = Field(default=None, pattern=r"^[a-f0-9]{12}$")


class ProviderAuthApiDomain(DomainBase):
    def sync_codex_credentials(self, payload: CodexCredentialSyncRequest) -> dict:
        try:
            result = sync_local_codex_credentials(account_id=payload.accountId)
            return {**result, "status": provider_status("openai")}
        except (CodexOAuthError, AuthStoreError) as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def get_api_key_aliases(self) -> dict:
        path = api_key_store_path(workspace_settings.get_workspace_root())
        try:
            return {"names": list_api_key_names(path)}
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=f"failed to read API key aliases: {exc}") from exc

    def add_api_key_alias(self, payload: dict) -> dict:
        path = api_key_store_path(workspace_settings.get_workspace_root())
        try:
            names = add_api_key_alias(
                path,
                name=payload.get("name"),
                api_key=payload.get("apiKey"),
            )
        except FileExistsError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except ApiKeyAliasValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(status_code=500, detail=f"failed to save API key alias: {exc}") from exc
        return {"names": names, "selected": str(payload.get("name") or "")}

    def get_codex_status(self) -> dict:
        return authorization_status()

    def start_codex_login(self) -> dict:
        try:
            return login_manager.start()
        except CodexOAuthError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def get_provider_status(self, provider_id: str) -> dict:
        try:
            return provider_status(provider_id)
        except (ProviderAuthorizationError, ValueError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def start_provider_login(self, provider_id: str) -> dict:
        try:
            return start_login(provider_id)
        except ProviderAuthorizationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def add_provider_api_key(self, provider_id: str, payload: dict) -> dict:
        try:
            return add_api_key_account(
                provider_id,
                api_key=str(payload.get("apiKey") or ""),
                alias=str(payload.get("alias") or ""),
                identity=str(payload.get("identity") or ""),
            )
        except ProviderAuthorizationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def submit_provider_login_code(self, provider_id: str, payload: dict) -> dict:
        try:
            return submit_login_code(provider_id, str(payload.get("code") or ""))
        except ProviderAuthorizationError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    def activate_provider_account(self, provider_id: str, account_id: str) -> dict:
        try:
            return activate_account(provider_id, account_id)
        except ProviderAuthorizationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    def delete_provider_account(self, provider_id: str, account_id: str) -> dict:
        try:
            return delete_account(provider_id, account_id)
        except ProviderAuthorizationError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["ProviderAuthApiDomain"]
