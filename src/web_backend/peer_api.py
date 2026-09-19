from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, Request
from pydantic import ValidationError

from src.peer_network.contracts import DeviceSetup, PeerCall, PeerGrant
from src.peer_network.service import PeerNetworkService
from src.peer_network.delivery import DeliveryJournal

from . import runtime_paths
from .peer_operations import PeerOperations
from .request_access import is_local_request, is_cloud_board_administrator


class PeerApiDomain:
    def __init__(self, core):
        self.core = core
        self._service: PeerNetworkService | None = None
        self.board_dispatch = None

    @property
    def service(self) -> PeerNetworkService:
        if self._service is None:
            root = Path(runtime_paths._get_runtime_root()) / ".auth" / "peer-network"
            self._service = PeerNetworkService(root, PeerOperations(self.core, DeliveryJournal(root / "deliveries.sqlite3")))
            self._service.board_dispatch = self.board_dispatch
        return self._service

    async def start(self) -> None:
        await self.service.start()

    async def close(self) -> None:
        if self._service is not None:
            await self._service.stop()

    @staticmethod
    def require_local(request: Request) -> None:
        if is_cloud_board_administrator(request):
            return
        if not is_local_request(request):
            raise HTTPException(403, "Manage peer connections from the local AgentPark backend.")
        # Browser cross-origin form requests must not mutate local trust settings.
        from urllib.parse import urlsplit
        host = request.headers.get("host", "")
        if urlsplit("http://" + host).hostname not in {"localhost", "127.0.0.1", "::1"}:
            raise HTTPException(403, "Open peer management using a loopback hostname.")
        origin = request.headers.get("origin")
        if origin:
            if urlsplit(origin).netloc != request.headers.get("host"):
                raise HTTPException(403, "Peer management requires the same origin.")

    async def get_status(self, request: Request):
        self.require_local(request)
        return self.service.status()

    async def configure(self, payload: dict, request: Request):
        self.require_local(request)
        try:
            await self.service.configure(DeviceSetup.model_validate(payload).connection_settings())
        except (ValueError, ImportError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return self.service.status()

    async def grant(self, payload: dict, request: Request):
        self.require_local(request)
        try:
            await self.service.grant(PeerGrant.model_validate(payload))
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return self.service.status()

    async def revoke(self, peer_id: str, request: Request):
        self.require_local(request)
        try:
            await self.service.revoke(peer_id)
        except KeyError as exc:
            raise HTTPException(404, "Device is not paired.") from exc
        return self.service.status()

    async def connect(self, peer_id: str, request: Request):
        self.require_local(request)
        try:
            await self.service.connect(peer_id)
        except (ValueError, PermissionError, ConnectionError, ImportError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc
        return self.service.status()

    async def call(self, peer_id: str, payload: dict, request: Request):
        self.require_local(request)
        try:
            call = PeerCall.model_validate(payload)
            return await self.service.call(peer_id, call)
        except ValidationError as exc:
            raise HTTPException(400, str(exc)) from exc
        except (ValueError, RuntimeError, PermissionError, ConnectionError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc


def register_peer_routes(app, core) -> None:
    from .peer_board_http import PeerBoardHttp
    api = core.peer_api
    api.board_dispatch = PeerBoardHttp(core, app)
    if api._service is not None:
        api._service.board_dispatch = api.board_dispatch
    app.get("/api/peers")(api.get_status)
    app.put("/api/peers/settings")(api.configure)
    app.put("/api/peers/grants")(api.grant)
    app.delete("/api/peers/{peer_id}")(api.revoke)
    app.post("/api/peers/{peer_id}/connect")(api.connect)
    app.post("/api/peers/{peer_id}/call")(api.call)
