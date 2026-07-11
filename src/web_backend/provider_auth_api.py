from fastapi import HTTPException

from src.provider_auth.codex_oauth import CodexOAuthError, authorization_status, login_manager

from .domain_base import DomainBase


class ProviderAuthApiDomain(DomainBase):
    def get_codex_status(self) -> dict:
        return authorization_status()

    def start_codex_login(self) -> dict:
        try:
            return login_manager.start()
        except CodexOAuthError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc


__all__ = ["ProviderAuthApiDomain"]
