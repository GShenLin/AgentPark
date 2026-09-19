from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path

from .connections import PeerConnections
from .contracts import NetworkSettings, PeerCall, PeerGrant, PortalTicket, Signal
from .identity import DeviceIdentity, peer_id, verify, verify_signal
from .store import PeerStore
from .ice import CREDENTIAL_SECONDS, REFRESH_SECONDS, IceLease


LOGGER = logging.getLogger(__name__)


class PeerNetworkService:
    def __init__(self, root: Path, dispatch):
        self.store = PeerStore(root)
        self.identity = DeviceIdentity.load(root / "identity.json")
        self.dispatch = dispatch
        self.connections = PeerConnections(self)
        self.errors: dict[str, str] = {}
        self.coordinator_error = ""
        self.enrollment_state = "disconnected"
        self.socket = None
        self.task: asyncio.Task | None = None
        self.send_lock = asyncio.Lock()
        self.signal_lock = asyncio.Lock()
        self.coordinator_public_key = ""
        self.portal_tickets: dict[str, PortalTicket] = {}
        self.board_dispatch = None
        self.ice_lease: IceLease | None = None

    async def start(self) -> None:
        if self.store.settings.enabled and self.task is None:
            import aiortc  # Fail explicitly when the installation is incomplete.
            self.task = asyncio.create_task(self.run(), name="agentpark-peer-network")

    async def stop(self) -> None:
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
            self.task = None
        await self.connections.close()
        self.portal_tickets.clear()
        self.ice_lease = None

    async def configure(self, settings: NetworkSettings) -> None:
        if settings.enabled:
            if not settings.signaling_url:
                raise ValueError("请填写鉴权服务器 IP。")
            import aiortc
        await self.stop()
        self.enrollment_state = "disconnected"
        self.store.settings = settings
        self.store.save()
        self.coordinator_error = ""
        await self.start()

    async def grant(self, grant: PeerGrant) -> None:
        if grant.peer_id == self.identity.peer_id:
            raise ValueError("Cannot pair this device with itself.")
        if grant.peer_id not in self.store.grants and len(self.store.grants) >= 100:
            raise ValueError("At most 100 paired devices are supported.")
        self.store.grants[grant.peer_id] = grant
        self.store.save()

    async def revoke(self, peer: str) -> None:
        if peer not in self.store.grants:
            raise KeyError("Device is not paired.")
        del self.store.grants[peer]
        self.store.save()
        await self.connections.remove(peer)

    async def send_signal(self, kind: str, peer: str, session: str, sdp: str = "") -> None:
        if self.socket is None:
            raise ConnectionError("Connection coordinator is not connected.")
        async with self.send_lock:
            await self.socket.send(json.dumps(self.identity.signal(kind, peer, session, sdp)))

    async def connect(self, peer: str) -> None:
        async with self.signal_lock:
            await self.connections.connect(peer)

    async def accept_portal(self, packet: dict) -> None:
        if not self.store.settings.portal_board or self.board_dispatch is None:
            raise PermissionError("Cloud Board access is disabled on this device.")
        ticket = PortalTicket.model_validate(packet["ticket"])
        verify(self.coordinator_public_key, ticket.signature, ticket.model_dump(exclude={"signature"}))
        signal = Signal.model_validate(packet["signal"])
        browser = verify_signal(signal, self.identity.peer_id)
        if ticket.target != self.identity.peer_id or ticket.browser_id != browser or ticket.session_id != signal.session_id:
            raise ValueError("Portal ticket is not bound to this browser and device session.")
        if not 0 < ticket.expires_at - time.time() <= 3600 or signal.kind != "offer":
            raise ValueError("Portal access has expired.")
        self.portal_tickets[browser] = ticket
        await self.connections.accept(packet["signal"], portal=True)

    async def dispatch_portal(self, browser: str, call: PeerCall) -> dict:
        ticket = self.portal_tickets.get(browser)
        if not self.store.settings.portal_board or ticket is None or ticket.expires_at <= time.time():
            raise PermissionError("Cloud Board session expired or was revoked.")
        if call.operation != "board_http" or call.http is None:
            raise PermissionError("Browser sessions can only access Board APIs.")
        return await self.board_dispatch(browser, call.http)

    async def call(self, peer: str, call: PeerCall) -> dict:
        if peer not in self.store.grants:
            raise PermissionError("Device is not paired.")
        link = self.connections.links.get(peer)
        if not link or not link.channel or self.connections.status(peer) != "connected":
            raise ConnectionError("Device is not connected. Connect it before sending requests.")
        return await link.channel.call(call)

    def status(self) -> dict:
        return {"peer_id": self.identity.peer_id, "settings": self.store.public_settings(),
                "coordinator_connected": self.socket is not None, "error": self.coordinator_error,
                "enrollment_state": self.enrollment_state,
                "device_name": self.store.settings.display_name,
                "peers": [{**grant.model_dump(), "state": self.connections.status(peer),
                           "error": self.errors.get(peer, "")}
                          for peer, grant in self.store.grants.items()]}

    async def run(self) -> None:
        from websockets.asyncio.client import connect
        delay = 1
        while True:
            try:
                settings = self.store.settings
                async with connect(settings.signaling_url, max_size=100000, ping_interval=20) as socket:
                    challenge = json.loads(await asyncio.wait_for(socket.recv(), 10))
                    if set(challenge) != {"kind", "challenge"} or challenge["kind"] != "challenge":
                        raise ValueError("Invalid coordinator challenge.")
                    metadata = {"display_name": settings.display_name, "portal_board": settings.portal_board, "stun_urls": settings.stun_urls}
                    await socket.send(json.dumps({"public_key": self.identity.public_key, **metadata,
                                                 "signature": self.identity.sign({"challenge": challenge["challenge"], **metadata})}))
                    ready = json.loads(await asyncio.wait_for(socket.recv(), 10))
                    if ready.get("kind") == "enrollment":
                        if set(ready) != {"kind", "state", "peer_id"} or ready["peer_id"] != self.identity.peer_id or ready["state"] not in {"pending", "rejected"}:
                            raise ValueError("Invalid device enrollment response.")
                        self.enrollment_state = ready["state"]
                        self.coordinator_error = ""
                        await self.connections.close()
                        self.portal_tickets.clear()
                        await socket.close()
                        await asyncio.sleep(5 if ready["state"] == "pending" else 30)
                        continue
                    if set(ready) != {"kind", "peer_id", "coordinator_public_key", "ice"} or ready["kind"] != "ready" or ready["peer_id"] != self.identity.peer_id:
                        raise ValueError("Coordinator identity acknowledgement is invalid.")
                    peer_id(ready["coordinator_public_key"])
                    self.coordinator_public_key = ready["coordinator_public_key"]
                    self.ice_lease = IceLease.model_validate(ready["ice"])
                    self.ice_lease.require_fresh()
                    self.socket = socket
                    self.enrollment_state = "approved"
                    self.coordinator_error = ""
                    delay = 1
                    retry_task = asyncio.create_task(self.maintain_connections())
                    try:
                        async for raw in socket:
                            packet = json.loads(raw)
                            if packet.get("kind") == "ice":
                                if set(packet) != {"kind", "ice"}:
                                    raise ValueError("Invalid ICE credential response.")
                                lease = IceLease.model_validate(packet["ice"])
                                lease.require_fresh()
                                self.ice_lease = lease
                            elif packet.get("kind") == "unavailable":
                                self.errors[packet["peer_id"]] = "Peer is offline at the coordinator."
                            elif packet.get("kind") == "portal_close":
                                browser = packet["peer_id"]
                                self.portal_tickets.pop(browser, None)
                                if browser in self.connections.links and self.connections.links[browser].portal:
                                    await self.connections.remove(browser)
                            elif packet.get("kind") in {"signal", "portal_signal"}:
                                try:
                                    async with self.signal_lock:
                                        if packet["kind"] == "portal_signal":
                                            await self.accept_portal(packet)
                                        else:
                                            await self.connections.accept(packet["signal"])
                                except Exception as exc:
                                    self.coordinator_error = f"Peer signal rejected: {type(exc).__name__}: {exc}"
                                    LOGGER.warning("Peer signaling rejected: %s", exc)
                            else:
                                raise ValueError("Unknown coordinator packet.")
                    finally:
                        retry_task.cancel()
                        await asyncio.gather(retry_task, return_exceptions=True)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self.enrollment_state = "disconnected"
                self.coordinator_error = f"{type(exc).__name__}: {exc}"
                LOGGER.warning("Peer coordinator connection failed: %s", self.coordinator_error)
            finally:
                self.socket = None
            # Existing authenticated data channels survive coordinator interruptions.
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)

    async def maintain_connections(self) -> None:
        while True:
            if self.ice_lease and self.ice_lease.expires_at - time.time() < CREDENTIAL_SECONDS - REFRESH_SECONDS:
                async with self.send_lock:
                    await self.socket.send(json.dumps({"kind": "ice_refresh"}))
            for peer in list(self.store.grants):
                if self.connections.status(peer) != "connected":
                    try:
                        await self.connect(peer)
                        self.errors.pop(peer, None)
                    except Exception as exc:
                        self.errors[peer] = f"{type(exc).__name__}: {exc}"
                        LOGGER.warning("Peer connection failed: %s", self.errors[peer])
            await asyncio.sleep(45)
