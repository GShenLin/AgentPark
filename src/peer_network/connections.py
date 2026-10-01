from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass

from .channel import PeerChannel
from .contracts import Signal
from .identity import verify_signal


@dataclass
class Link:
    session_id: str
    pc: object
    created_at: float
    channel: PeerChannel | None = None
    portal: bool = False


class PeerConnections:
    def __init__(self, service):
        self.service = service
        self.links: dict[str, Link] = {}
        self.seen: dict[tuple[str, str, str], float] = {}
        self.changed = asyncio.Event()

    async def remove(self, peer: str) -> None:
        link = self.links.pop(peer, None)
        if link:
            if link.channel:
                link.channel.close()
            await link.pc.close()
        self.changed.set()

    async def close(self) -> None:
        for peer in list(self.links):
            await self.remove(peer)

    async def new(self, peer: str, session_id: str) -> Link:
        from aiortc import RTCConfiguration, RTCIceServer, RTCPeerConnection
        await self.remove(peer)
        # An explicit empty list disables aiortc's default public STUN service.
        servers = [RTCIceServer(urls=url) for url in self.service.store.settings.stun_urls]
        if self.service.ice_lease is not None:
            self.service.ice_lease.require_fresh()
            servers.extend(RTCIceServer(**server.model_dump()) for server in self.service.ice_lease.ice_servers)
        pc = RTCPeerConnection(RTCConfiguration(iceServers=servers))
        link = Link(session_id, pc, time.monotonic())
        self.links[peer] = link
        self.changed.set()

        @pc.on("datachannel")
        def on_channel(channel):
            if channel.label != "agentpark.v1" or link.channel is not None or not channel.ordered:
                channel.close()
                return
            self.bind(peer, link, channel)

        @pc.on("connectionstatechange")
        def state_changed():
            self.changed.set()
            if pc.connectionState == "failed":
                self.service.errors[peer] = "设备连接失败，请检查网络及云端 STUN/TURN 服务是否可达。"
                if link.channel:
                    link.channel.close()

        return link

    def bind(self, peer: str, link: Link, channel) -> None:
        async def dispatch(call):
            if link.portal:
                return await self.service.dispatch_portal(peer, call)
            if call.operation == "remote_workspace":
                return await self.service.remote.accept(peer, call)
            # Resolve grants for every operation, including already established sessions.
            grant = self.service.store.grants.get(peer)
            if grant is None:
                raise PermissionError("Peer authorization has been revoked.")
            return await self.service.dispatch(grant, call)
        link.channel = PeerChannel(channel, dispatch)
        channel.on("open", self.changed.set)
        channel.on("close", self.changed.set)
        self.changed.set()

    async def wait_connected(self, peer: str, timeout: float = 35) -> Link:
        async with asyncio.timeout(timeout):
            while True:
                self.changed.clear()
                link = self.links.get(peer)
                if link and link.channel and link.channel.ready.is_set() and not link.channel.closed:
                    return link
                if link and link.pc.connectionState in {"failed", "closed"}:
                    raise ConnectionError("Remote peer connection failed.")
                await self.changed.wait()

    async def connect(self, peer: str) -> None:
        if peer not in self.service.store.grants and not self.service.remote.allows_connection(peer):
            raise PermissionError("Pair the device before connecting.")
        existing = self.links.get(peer)
        if existing and existing.pc.connectionState not in {"closed", "failed"}:
            if time.monotonic() - existing.created_at < 40 or existing.pc.connectionState == "connected":
                return
        if self.service.identity.peer_id > peer:
            await self.service.send_signal("connect", peer, uuid.uuid4().hex)
            return
        link = await self.new(peer, uuid.uuid4().hex)
        self.bind(peer, link, link.pc.createDataChannel("agentpark.v1", ordered=True))
        async with asyncio.timeout(30):
            await link.pc.setLocalDescription(await link.pc.createOffer())
        await self.service.send_signal("offer", peer, link.session_id, link.pc.localDescription.sdp)

    async def accept(self, raw: dict, *, portal: bool = False) -> None:
        from aiortc import RTCSessionDescription
        signal = Signal.model_validate(raw)
        peer = verify_signal(signal, self.service.identity.peer_id)
        if not portal and peer not in self.service.store.grants and not self.service.remote.allows_connection(peer):
            raise PermissionError("Signal from unpaired device rejected.")
        now = time.time()
        self.seen = {key: expiry for key, expiry in self.seen.items() if expiry > now}
        key = (peer, signal.kind, signal.session_id)
        if key in self.seen:
            raise ValueError("Replayed peer signal.")
        self.seen[key] = signal.expires_at
        if signal.kind == "connect":
            if peer < self.service.identity.peer_id:
                raise ValueError("Only the designated responder can request an offer.")
            await self.connect(peer)
        elif signal.kind == "offer":
            if not portal and peer > self.service.identity.peer_id:
                raise ValueError("Offer from a non-designated initiator.")
            old = self.links.get(peer)
            if old and old.pc.connectionState == "connected":
                raise ValueError("Existing connection is still active.")
            link = await self.new(peer, signal.session_id)
            link.portal = portal
            async with asyncio.timeout(30):
                await link.pc.setRemoteDescription(RTCSessionDescription(sdp=signal.sdp, type="offer"))
                await link.pc.setLocalDescription(await link.pc.createAnswer())
            await self.service.send_signal("answer", peer, signal.session_id, link.pc.localDescription.sdp)
        else:
            link = self.links.get(peer)
            if link is None or link.session_id != signal.session_id or link.pc.signalingState != "have-local-offer":
                raise ValueError("Answer does not match the pending connection.")
            await link.pc.setRemoteDescription(RTCSessionDescription(sdp=signal.sdp, type="answer"))

    def status(self, peer: str) -> str:
        link = self.links.get(peer)
        if link is None:
            return "disconnected"
        if link.channel and link.channel.ready.is_set() and not link.channel.closed:
            return "connected"
        # ICE can become connected before SCTP opens the RPC data channel.
        return "connecting" if link.pc.connectionState == "connected" else link.pc.connectionState
