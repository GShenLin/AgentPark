import asyncio
import base64
import time
from types import SimpleNamespace

from fastapi import FastAPI

import pytest

from src.peer_network.channel import PeerChannel
from src.peer_network.connections import Link
from src.peer_network.contracts import BoardHttpRequest, DeviceSetup, PeerCall, WireRequest
from src.public_gateway.request_diagnostics import register_request_diagnostics
from src.web_backend.peer_api import PeerApiDomain, register_peer_routes
from src.peer_network.service import PeerNetworkService
from src.peer_network.store import PeerStore


class DataChannel:
    readyState = "open"

    def on(self, *args):
        pass

    def send(self, data):
        raise AssertionError("A closed channel cannot return a response")


class PeerConnection:
    closed = False

    async def close(self):
        # Transport shutdown yields to the loop, exposing self-cancellation.
        await asyncio.sleep(0)
        self.closed = True


@pytest.mark.parametrize("enabled", [False, True])
@pytest.mark.parametrize("through_http", [False, True])
def test_remote_settings_finish_when_they_close_their_own_channel(tmp_path, enabled, through_http):
    async def scenario():
        service = PeerNetworkService(tmp_path, None)
        settings = DeviceSetup(enabled=enabled, display_name="Renamed device").connection_settings()

        async def dispatch(call):
            await service.configure(settings)
            return service.status()

        if through_http:
            app = FastAPI()
            register_request_diagnostics(app, None)

            core = SimpleNamespace()
            core.peer_api = PeerApiDomain(core)
            core.peer_api._service = service
            register_peer_routes(app, core)
            body = DeviceSetup(enabled=enabled, display_name="Renamed device").model_dump_json().encode()

            async def dispatch(call):
                return await core.peer_api.board_dispatch("browser", BoardHttpRequest(
                    method="PUT", path="/api/peers/settings",
                    headers={"content-type": "application/json"},
                    body=base64.b64encode(body).decode(),
                ))

        channel = PeerChannel(DataChannel(), dispatch)
        pc = PeerConnection()
        service.connections.links["browser"] = Link("session", pc, time.monotonic(), channel, True)
        async def run():
            await asyncio.sleep(60)

        service.run = run
        service.task = asyncio.create_task(asyncio.sleep(60))
        other = asyncio.create_task(asyncio.sleep(60))
        request = WireRequest(request_id="a" * 32, call=PeerCall(operation="graphs"))
        current = asyncio.create_task(channel.handle(request))
        channel.tasks.update((current, other))
        results = await asyncio.gather(current, other, return_exceptions=True)
        assert results[0] is None
        assert isinstance(results[1], asyncio.CancelledError)
        assert pc.closed
        assert (service.task is not None) == enabled
        assert not service.connections.links
        assert PeerStore(tmp_path).settings.display_name == "Renamed device"
        assert PeerStore(tmp_path).settings.enabled == enabled
        await service.stop()

    asyncio.run(scenario())
