from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone

from fastapi import WebSocket


@dataclass
class DeviceConnection:
    socket: WebSocket
    display_name: str
    portal_board: bool
    stun_urls: list[str] = field(default_factory=list)
    connected_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    remote_workers: list[dict] = field(default_factory=list)
    remote_directory_enabled: bool = False


class CoordinatorRegistry:
    def __init__(self):
        self.devices: dict[str, DeviceConnection] = {}
        self.browsers: dict[str, WebSocket] = {}
        self.browser_locks: dict[str, asyncio.Lock] = {}
        self.browser_targets: dict[str, str] = {}

    async def send_device(self, device_id: str, data: dict) -> None:
        device = self.devices.get(device_id)
        if device is None:
            raise ConnectionError("Device is offline.")
        async with device.lock:
            await device.socket.send_json(data)

    async def send_browser(self, browser_id: str, data: dict) -> None:
        socket = self.browsers.get(browser_id)
        if socket is None:
            raise ConnectionError("Browser session is disconnected.")
        async with self.browser_locks[browser_id]:
            await socket.send_json(data)

    def snapshot(self) -> list[dict]:
        return [{"peer_id": peer, "name": device.display_name, "connected_at": device.connected_at,
                 "portal_board": device.portal_board, "stun_urls": device.stun_urls, "state": "online"}
                for peer, device in sorted(self.devices.items(), key=lambda item: item[1].connected_at)]

    async def publish_remote_directory(self) -> None:
        # Only authenticated, admitted devices receive the directory. Browser
        # sessions continue to access it through their selected Board backend.
        packet = {"kind": "remote_directory", "hosts": [
            {"peer_id": peer, "remote_workers": device.remote_workers}
            for peer, device in self.devices.items()
            if device.remote_directory_enabled
        ]}
        for peer, device in list(self.devices.items()):
            if device.remote_directory_enabled:
                try:
                    await self.send_device(peer, packet)
                except (RuntimeError, ConnectionError):
                    # The owning websocket handler removes disconnected devices.
                    import logging
                    logging.getLogger(__name__).warning("Remote directory delivery failed for %s", peer)
