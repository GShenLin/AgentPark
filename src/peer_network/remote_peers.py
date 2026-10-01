"""Directory ownership and execution routing for coordinator-admitted devices."""
from __future__ import annotations

import asyncio
import json
import time

from .contracts import PeerCall
from .remote_contracts import RemoteHost, RemoteRequest, validate_descriptors


class RemotePeers:
    def __init__(self, service):
        self.service = service
        self.hosts: dict[str, RemoteHost] = {}
        self.provider = lambda: []
        self.dispatch = None
        self._published = None
        self._changed = asyncio.Event()

    def reset(self) -> None:
        self.hosts = {}
        self._published = None
        self._changed.set()

    async def publish(self) -> None:
        workers = validate_descriptors(self.provider())
        if self._published == workers:
            return
        async with self.service.send_lock:
            await self.service.socket.send(json.dumps(
                {"kind": "remote_publish", "remote_workers": workers}, ensure_ascii=False,
            ))
        self._published = workers

    def receive(self, packet: dict) -> None:
        if set(packet) != {"kind", "hosts"} or not isinstance(packet["hosts"], list):
            raise ValueError("Invalid remote directory.")
        hosts = [RemoteHost.model_validate(item) for item in packet["hosts"]]
        if len(hosts) > 100 or len({host.peer_id for host in hosts}) != len(hosts):
            raise ValueError("Invalid remote host identities.")
        self.hosts = {host.peer_id: host for host in hosts}
        self._changed.set()

    def allows_connection(self, peer: str) -> bool:
        if self.service.socket is None or peer not in self.hosts:
            return False
        # Automatic trust only opens a remote execution channel. Ordinary peer
        # operations still resolve their explicit grants on every call.
        return bool(self.hosts[peer].remote_workers or self.provider())

    def workers(self) -> list[dict]:
        return [{**worker.model_dump(), "worker_id": f"peer:{host.peer_id}:{worker.worker_id}",
                 "connection_kind": "coordinator", "host_peer_id": host.peer_id}
                for host in self.hosts.values() if host.peer_id != self.service.identity.peer_id
                for worker in host.remote_workers]

    @staticmethod
    def split_target(worker_id: str) -> tuple[str, str]:
        parts = worker_id.split(":", 2)
        if len(parts) != 3 or parts[0] != "peer" or len(parts[1]) != 64 or not parts[2]:
            raise ValueError("Invalid coordinator remote identity.")
        return parts[1], parts[2]

    async def wait_online(self, worker_id: str, timeout: float) -> dict:
        deadline = time.monotonic() + max(0, min(timeout, 30))
        while True:
            self._changed.clear()
            worker = next((w for w in self.workers() if w["worker_id"] == worker_id and w["online"]), None)
            if worker is not None:
                return worker
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise LookupError("Remote device is offline or is not admitted by this coordinator.")
            try:
                await asyncio.wait_for(self._changed.wait(), remaining)
            except TimeoutError as exc:
                raise LookupError("Remote device did not reconnect in time.") from exc

    async def accept(self, peer: str, call: PeerCall) -> dict:
        if not self.allows_connection(peer) or self.dispatch is None or call.remote is None:
            raise PermissionError("Remote execution is not authorized for this device.")
        owned = {worker["worker_id"] for worker in self.provider()}
        if call.remote.worker_id not in owned:
            raise PermissionError("The requested worker does not belong to this host.")
        return await self.dispatch(peer, call.remote)

    async def call(self, worker_id: str, request: RemoteRequest) -> dict:
        host, worker = self.split_target(worker_id)
        await self.wait_online(worker_id, 5)
        await self.service.connect(host)
        link = await self.service.connections.wait_connected(host)
        return await link.channel.call(PeerCall(
            operation="remote_workspace", remote=request.model_copy(update={"worker_id": worker}),
        ))
