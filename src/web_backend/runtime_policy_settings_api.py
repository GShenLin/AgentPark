from __future__ import annotations

from src.runtime_policy.contracts import RuntimePolicyValidationError
from src.runtime_policy.settings_store import RuntimePolicySettingsStore

from .domain_base import DomainBase
from .shared import HTTPException


class RuntimePolicySettingsApiDomain(DomainBase):
    def get_settings(self):
        try:
            return RuntimePolicySettingsStore().load()
        except RuntimePolicyValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"failed to read RuntimePolicy settings: {exc}",
            ) from exc

    def update_default(self, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be an object")
        unknown = sorted(set(payload) - {"policy_id"})
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown RuntimePolicy default fields: {', '.join(unknown)}",
            )
        try:
            return RuntimePolicySettingsStore().update_default(payload.get("policy_id"))
        except RuntimePolicyValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"failed to update the default RuntimePolicy: {exc}",
            ) from exc

    def update_policy(self, policy_id: str, payload: dict):
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="payload must be an object")
        unknown = sorted(set(payload) - {"config"})
        if unknown:
            raise HTTPException(
                status_code=400,
                detail=f"unknown RuntimePolicy config fields: {', '.join(unknown)}",
            )
        try:
            return RuntimePolicySettingsStore().update_policy(
                policy_id,
                payload.get("config"),
            )
        except RuntimePolicyValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(
                status_code=500,
                detail=f"failed to update RuntimePolicy {policy_id!r}: {exc}",
            ) from exc


__all__ = ["RuntimePolicySettingsApiDomain"]
