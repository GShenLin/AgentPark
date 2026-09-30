"""Administrator portal client using the same signed Board tickets as the browser."""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import ssl
import uuid

import tempfile
from pathlib import Path
from src.providers.curl_transport import CurlHttpTransport
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from websockets.asyncio.client import connect

from .channel import PeerChannel
from .contracts import BoardHttpRequest, PeerCall, Signal
from .ice import IceLease
from .identity import DeviceIdentity, verify_signal

LOGGER = logging.getLogger(__name__)
SYNC_OPERATIONS = frozenset({"catalog", "create-graph", "export", "blob-status", "blob-read", "blob-write", "prepare", "apply"})


class PortalBoardConnection:
    def __init__(self):
        self.socket = None
        self.pc = None
        self.rpc = None
        self.listener = None
        self.pc_close_task = None

    @classmethod
    async def open(cls, client: "PortalClient", device: dict):
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection, RTCSessionDescription
        connection = cls()
        identity = DeviceIdentity(Ed25519PrivateKey.generate())
        session_id = uuid.uuid4().hex
        try:
            async with asyncio.timeout(45):
                url = client.origin.replace("https://", "wss://").replace("http://", "ws://") + "/portal/connect"
                cookie = CurlHttpTransport.cookie_header(client.cookie_file, client.origin + "/portal/connect")
                connection.socket = await connect(url, origin=client.origin,
                    additional_headers={"Cookie": cookie},
                    ssl=client.tls if url.startswith("wss:") else None, proxy=None, max_size=100000)
                socket = connection.socket
                challenge = json.loads(await socket.recv())
                if set(challenge) != {"kind", "challenge"} or challenge["kind"] != "challenge":
                    raise ValueError("Invalid portal challenge.")
                await socket.send(json.dumps({"public_key": identity.public_key,
                    "signature": identity.sign({"challenge": challenge["challenge"]})}))
                ready = json.loads(await socket.recv())
                if ready.get("kind") != "ready" or ready.get("peer_id") != identity.peer_id:
                    raise ValueError("Invalid portal acknowledgement.")
                lease = IceLease.model_validate(ready["ice"])
                lease.require_fresh()
                urls = device["stun_urls"]
                if any(not url.startswith("stun:") for url in urls):
                    raise ValueError("Invalid device discovery address.")
                servers = [RTCIceServer(urls=url) for url in urls]
                servers.extend(RTCIceServer(**server.model_dump()) for server in lease.ice_servers)
                connection.pc = pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))

                async def reject_incoming(call):
                    raise PermissionError("This connection only issues administrator requests.")

                connection.rpc = PeerChannel(pc.createDataChannel("agentpark.v1", ordered=True), reject_incoming)
                await pc.setLocalDescription(await pc.createOffer())
                await socket.send(json.dumps(identity.signal("offer", device["peer_id"], session_id, pc.localDescription.sdp)))
                packet = json.loads(await socket.recv())
                if packet.get("kind") == "error":
                    raise ConnectionError(packet["error"])
                if packet.get("kind") != "signal":
                    raise ValueError("Invalid portal answer.")
                signal = Signal.model_validate(packet["signal"])
                if (verify_signal(signal, identity.peer_id) != device["peer_id"]
                        or signal.session_id != session_id or signal.kind != "answer"):
                    raise ValueError("Device answer identity or session mismatch.")
                await pc.setRemoteDescription(RTCSessionDescription(sdp=signal.sdp, type="answer"))
                await connection.rpc.ready.wait()
                if connection.rpc.closed:
                    raise ConnectionError("Remote device disconnected during connection.")
            connection.listener = asyncio.create_task(connection.watch())
            return connection
        except BaseException:
            await connection.close()
            raise

    async def watch(self):
        try:
            async for _ in self.socket:
                raise ValueError("Unexpected portal signaling after connection.")
        except Exception as exc:
            # The next RPC reports a disconnected channel; never replay a write.
            LOGGER.warning("Sync Board signaling ended: %s", type(exc).__name__)
            self.rpc.close()
        finally:
            self.rpc.close()
            await self.close_pc()

    async def close_pc(self):
        # aiortc close must finish once started. Cancelling it mid-close leaves
        # its internal completion future unresolved and later closes hang.
        if self.pc:
            if self.pc_close_task is None:
                self.pc_close_task = asyncio.create_task(self.pc.close())
            await asyncio.shield(self.pc_close_task)

    async def close(self):
        if self.listener:
            self.listener.cancel()
            await asyncio.gather(self.listener, return_exceptions=True)
        if self.rpc:
            self.rpc.close()
        await self.close_pc()
        if self.socket:
            await self.socket.close()


class PortalClient:
    def __init__(self, origin: str):
        self.origin = origin
        self.tls = ssl.create_default_context()  # Includes the installed Windows trust roots.
        self.http = CurlHttpTransport()
        self.cookie_dir = tempfile.TemporaryDirectory(prefix="agentpark-portal-")
        self.cookie_file = str(Path(self.cookie_dir.name) / "cookies")
        self.http_lock = asyncio.Lock()
        self.connections: dict[str, PortalBoardConnection] = {}
        self.lock = asyncio.Lock()

    async def _request(self, method, path, payload=None):
        async with self.http_lock:
            return await self.http.request_async(url=self.origin + path, method=method,
                body=json.dumps(payload).encode("utf-8") if payload is not None else None,
                headers={"Origin": self.origin, "Content-Type": "application/json"},
                trust_env=False, follow_redirects=False, timeout_sec=20, cookie_file=self.cookie_file,
                revocation_best_effort=True)

    async def login(self, password: str):
        response = await self._request("POST", "/portal/api/login", {"password": password})
        self.check(response)

    @staticmethod
    def check(response):
        if response.status_code == 401:
            raise ValueError("云端密码错误或登录已过期，请重新连接远程设备。")
        if response.status_code != 200 and response.status_code != 204:
            raise ValueError(f"云端设备中心请求失败（HTTP {response.status_code}）。")

    async def devices(self):
        response = await self._request("GET", "/portal/api/devices")
        self.check(response)
        return response.json()["devices"]

    async def call(self, peer_id: str, operation: str, payload: dict):
        if operation not in SYNC_OPERATIONS:
            raise ValueError("Unsupported sync operation.")
        async with self.lock:
            connection = self.connections.get(peer_id)
            if connection is None or connection.rpc.closed:
                if connection:
                    await connection.close()
                    del self.connections[peer_id]
                devices = await self.devices()
                device = next((d for d in devices if d["peer_id"] == peer_id), None)
                if device is None or not device["portal_board"]:
                    raise ValueError("远程设备离线或未启用云端访问，请刷新设备列表。")
                if len(self.connections) >= 2:
                    _, old = self.connections.popitem()
                    await old.close()
                connection = await PortalBoardConnection.open(self, device)
                self.connections[peer_id] = connection
            body = base64.b64encode(json.dumps(payload, ensure_ascii=False).encode()).decode()
            result = await connection.rpc.call(PeerCall(operation="board_http", http=BoardHttpRequest(
                method="POST", path=f"/api/node-sync/protocol/{operation}",
                headers={"content-type": "application/json"}, body=body)))
            raw = base64.b64decode(result["body"], validate=True)
            if result["status"] in {404, 405}:
                raise ValueError("远程设备尚不支持节点同步，请更新并重启该设备。")
            if not result["headers"].get("content-type", "").startswith("application/json"):
                raise ValueError("远程设备返回了非同步协议内容。")
            data = json.loads(raw)
            if result["status"] != 200:
                raise ValueError(f"远程设备：{data.get('detail', result['status'])}")
            return data

    async def close(self):
        for connection in self.connections.values():
            await connection.close()
        self.connections.clear()
        async with self.http_lock:
            self.cookie_dir.cleanup()

    async def logout(self):
        try:
            response = await self._request("POST", "/portal/api/logout")
            self.check(response)
        finally:
            await self.close()
