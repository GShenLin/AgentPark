"""In-memory portal sessions, scoped to the initiating administrator."""
from __future__ import annotations

import asyncio
import hashlib
import re
import threading
from urllib.parse import urlsplit

from fastapi import HTTPException
from src.providers.curl_transport import CurlTransportError
from pydantic import Field, SecretStr

from src.peer_network.portal_client import PortalClient
from src.web_backend.peer_api import PeerApiDomain
from src.web_backend.request_access import is_cloud_board_administrator
from .contracts import Contract, SyncConflict


class CloudLogin(Contract):
    password: SecretStr = Field(min_length=1, max_length=1024)


class CloudDevices:
    def __init__(self, core):
        self.core = core
        self.sessions: dict[str, PortalClient] = {}
        self.loop = None
        self.thread = None
        self.lock = threading.RLock()

    def owner(self, request):
        PeerApiDomain.require_local(request)
        # Portal tickets all represent the same coordinator administrator;
        # browser peer IDs change on reconnect and are not durable user IDs.
        return "cloud-administrator" if is_cloud_board_administrator(request) else "local"

    def origin(self):
        url = urlsplit(self.core.peer_api.service.store.settings.signaling_url)
        if not url.netloc:
            raise SyncConflict("请先在设备互联中填写云端鉴权服务器。")
        return ("https" if url.scheme == "wss" else "http") + "://" + url.netloc

    @staticmethod
    def prefix(origin):
        return "cloud:" + hashlib.sha256(origin.encode()).hexdigest()[:16] + ":"

    def run(self, factory):
        with self.lock:
            if self.loop is None:
                self.loop = asyncio.new_event_loop()
                self.thread = threading.Thread(target=self.loop.run_forever, daemon=True, name="node-sync-cloud")
                self.thread.start()
            future = asyncio.run_coroutine_threadsafe(factory(), self.loop)
        try:
            return future.result(180)
        except TimeoutError as exc:
            future.cancel()
            raise SyncConflict("远程设备请求超时，未自动重发；请检查设备连接后继续任务。") from exc
        except CurlTransportError as exc:
            raise SyncConflict(f"无法连接云端设备中心：{type(exc).__name__}。请检查服务器地址、网络和证书信任。") from exc
        except (OSError, RuntimeError) as exc:
            raise SyncConflict(str(exc)) from exc

    def status(self, request):
        owner = self.owner(request)
        with self.lock:
            client = self.sessions.get(owner)
            return {"connected": client is not None, "origin": client.origin if client else self.origin()}

    def login(self, request, password):
        owner, origin = self.owner(request), self.origin()

        async def connect():
            client = PortalClient(origin)
            try:
                await client.login(password)
                await client.devices()
            except BaseException:
                await client.close()
                raise
            with self.lock:
                old = self.sessions.pop(owner, None)
                self.sessions[owner] = client
            if old:
                await old.logout()
        self.run(connect)
        return self.status(request)

    def get(self, request):
        owner = self.owner(request)
        with self.lock:
            client = self.sessions.get(owner)
        if client is None:
            raise SyncConflict("请先连接云端设备中心，再选择远程设备。服务重启后需要重新登录。")
        return client

    def remotes(self, request):
        # LAN developers do not inherit a locally authenticated portal session.
        try:
            owner = self.owner(request)
        except HTTPException as exc:
            if exc.status_code == 403:
                return []
            raise
        with self.lock:
            client = self.sessions.get(owner)
        if client is None:
            return []
        devices = self.run(client.devices)
        return [{"id": self.prefix(client.origin) + d["peer_id"], "name": d["name"],
                 "kind": "cloud", "address": client.origin, "available": d["portal_board"],
                 "state": "在线" if d["portal_board"] else "未启用云端访问"} for d in devices]

    def call(self, remote_id, operation, payload, request):
        client = self.get(request)
        prefix = self.prefix(client.origin)
        peer = remote_id.removeprefix(prefix)
        if not remote_id.startswith(prefix) or not re.fullmatch(r"[a-f0-9]{64}", peer):
            raise SyncConflict("云端设备不属于当前登录的设备中心，请重新选择。")
        return self.run(lambda: client.call(peer, operation, payload))

    def logout(self, request):
        owner = self.owner(request)
        with self.lock:
            client = self.sessions.pop(owner, None)
        if client:
            self.run(client.logout)
        return self.status(request)

    def close(self):
        with self.lock:
            clients = list(self.sessions.values())
            self.sessions.clear()
        async def close_all():
            await asyncio.gather(*(client.close() for client in clients))
        if self.loop:
            self.run(close_all)
            self.loop.call_soon_threadsafe(self.loop.stop)
            self.thread.join(5)
            self.loop.close()
            self.loop = None
