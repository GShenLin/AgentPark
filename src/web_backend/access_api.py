from __future__ import annotations

from fastapi import Request

from src.access_policy import AccessPolicyError
from src.access_policy import access_policy_path
from src.access_policy import load_access_policy
from src.access_policy import register_remote_user
from src.access_policy import save_access_policy

from .request_access import is_local_request, is_cloud_board_administrator
from src.peer_network.principal import PeerPrincipal
from .shared import HTTPException


ACCESS_CLIENT_ID_HEADER = "x-agentpark-client-id"
ACCESS_USERNAME_HEADER = "x-agentpark-username"


class AccessApiDomain:
    def get_status(self, request: Request = None) -> dict:
        principal = getattr(getattr(request, "state", None), "peer_principal", None)
        if isinstance(principal, PeerPrincipal):
            administrator = is_cloud_board_administrator(request)
            return {
                "client_id": "peer:" + principal.peer_id,
                "username": principal.name,
                "role": "developer" if administrator else "nondeveloper",
                "is_developer": administrator,
                "is_local_client": False,
                "username_required": False,
                "ip": "peer:" + principal.peer_id,
            }
        if is_local_request(request):
            return {
                "client_id": "local",
                "username": "Local",
                "role": "developer",
                "is_developer": True,
                "is_local_client": True,
                "username_required": False,
                "ip": _client_ip(request),
            }

        client_id = _header(request, ACCESS_CLIENT_ID_HEADER)
        username = _header(request, ACCESS_USERNAME_HEADER)
        if not client_id or not username:
            return {
                "client_id": client_id,
                "username": username,
                "role": "nondeveloper",
                "is_developer": False,
                "is_local_client": False,
                "username_required": True,
                "ip": _client_ip(request),
            }
        try:
            user = register_remote_user(
                client_id=client_id,
                username=username,
                ip=_client_ip(request),
            )
        except AccessPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        is_developer = user.get("developer") is True
        return {
            "client_id": client_id,
            "username": user["username"],
            "role": "developer" if is_developer else "nondeveloper",
            "is_developer": is_developer,
            "is_local_client": False,
            "username_required": False,
            "ip": _client_ip(request),
        }

    def get_settings(self, request: Request = None) -> dict:
        self.require_developer(request)
        try:
            return {
                "path": access_policy_path(),
                "data": load_access_policy(),
            }
        except AccessPolicyError as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def update_settings(self, payload: dict, request: Request = None) -> dict:
        self.require_developer(request)
        try:
            data = save_access_policy(payload)
        except AccessPolicyError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "path": access_policy_path(),
            "data": data,
        }

    def require_developer(self, request: Request = None) -> dict:
        status = self.get_status(request)
        if status.get("is_developer") is not True:
            raise HTTPException(status_code=403, detail="Developer permission is required")
        return status

    def message_access_metadata(self, request: Request = None) -> dict[str, object]:
        status = self.get_status(request)
        if status.get("username_required") is True:
            raise HTTPException(status_code=401, detail="username registration is required")
        return {
            "_access_client_id": str(status.get("client_id") or ""),
            "_access_username": str(status.get("username") or ""),
            "_access_role": str(status.get("role") or "nondeveloper"),
            "_access_ip": str(status.get("ip") or ""),
        }


def _header(request: Request | None, name: str) -> str:
    if request is None:
        return ""
    return str(request.headers.get(name) or "").strip()


def _client_ip(request: Request | None) -> str:
    if request is None:
        return ""
    client = getattr(request, "client", None)
    return str(getattr(client, "host", "") or "").strip()


__all__ = [
    "ACCESS_CLIENT_ID_HEADER",
    "ACCESS_USERNAME_HEADER",
    "AccessApiDomain",
]
