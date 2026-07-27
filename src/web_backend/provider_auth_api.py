from fastapi import HTTPException

from src.provider_auth.codex_oauth import CodexOAuthError, authorization_status, login_manager
from src.provider_auth.service import (
    ProviderAuthorizationError,
    activate_account,
    add_api_key_account,
    delete_account,
    provider_status,
    start_login,
    submit_login_code,
)

from .domain_base import DomainBase


class ProviderAuthApiDomain(DomainBase):
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
