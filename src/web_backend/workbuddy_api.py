"""Settings API for the managed service and provider-specific account controls."""
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict, Field

from src.config_loader import ConfigLoader
from src.workspace_settings import get_workspace_root
from src.workbuddy.gateway import WorkBuddyError, WorkBuddyGateway
from src.workbuddy.manager import WorkBuddyServiceManager
from .domain_base import DomainBase


class ServiceAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["install", "start", "stop", "configure"]
    autoStart: bool = False
    port: int = Field(default=18788, ge=1024, le=65535)


class AccountAction(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    operation: Literal["status", "models", "login", "finish", "logout"]
    loginId: str = Field(default="", max_length=128)


class WorkBuddyApiDomain(DomainBase):
    def __init__(self, core):
        super().__init__(core)
        self._manager = WorkBuddyServiceManager(Path(get_workspace_root()))

    @property
    def manager(self) -> WorkBuddyServiceManager:
        return self._manager

    def status(self) -> dict:
        return self.manager.status()

    def service(self, payload: ServiceAction) -> dict:
        try:
            if payload.operation == "configure":
                return self.manager.configure(payload.autoStart, payload.port)
            return self.manager.begin(payload.operation)
        except (RuntimeError, ValueError) as exc:
            raise HTTPException(409, str(exc)) from exc

    def account(self, provider_id: str, payload: AccountAction) -> dict:
        try:
            config = ConfigLoader().get_provider_config(provider_id)
            if config.get("type") != "workbuddy":
                raise ValueError("此操作需要 WorkBuddy Provider。")
            gateway = WorkBuddyGateway(config)
            if payload.operation == "finish":
                if len(payload.loginId) < 16:
                    raise ValueError("Invalid WorkBuddy login ID")
                return gateway.finish(payload.loginId).model_dump()
            operations = {"status": gateway.status, "models": gateway.catalog,
                          "login": gateway.login, "logout": gateway.logout}
            return operations[payload.operation]().model_dump()
        except (ValueError, WorkBuddyError) as exc:
            raise HTTPException(409, str(exc)) from exc
