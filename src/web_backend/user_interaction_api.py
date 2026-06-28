from __future__ import annotations

from fastapi import HTTPException

from .domain_base import DomainBase
from src.user_interaction_store import list_interaction_requests, submit_interaction_response


class UserInteractionApiDomain(DomainBase):
    def list_user_interactions(self, status: str = "pending"):
        try:
            return {"requests": list_interaction_requests(status=status)}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def submit_user_interaction(self, request_id: str, payload: dict | None = None):
        body = payload if isinstance(payload, dict) else {}
        response = body.get("response") if isinstance(body.get("response"), dict) else body
        status = str(body.get("status") or "submitted")
        try:
            request = submit_interaction_response(request_id, response, status=status)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return {"ok": True, "request": request}
