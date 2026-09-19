"""Real coordinator + two independent aiortc endpoints, with relay disabled."""
import asyncio
import socket

import pytest

from src.peer_network.contracts import NetworkSettings, PeerCall, PeerGrant
from src.peer_network.service import PeerNetworkService
from src.peer_network.signaling import create_signaling_app
from src.peer_network.enrollment import DeviceAdmissions


def test_two_backends_exchange_data_directly_and_revoke(tmp_path):
    pytest.importorskip("aiortc")
    import uvicorn

    async def wait_for(predicate, seconds=20):
        async with asyncio.timeout(seconds):
            while not predicate():
                await asyncio.sleep(0.05)

    async def scenario():
        admissions = DeviceAdmissions(tmp_path / "coordinator" / "devices.json")
        sock = socket.socket()
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
        server = uvicorn.Server(uvicorn.Config(create_signaling_app(admissions=admissions), log_level="error", lifespan="on"))
        server_task = asyncio.create_task(server.serve(sockets=[sock]))
        seen = []

        async def dispatch(grant, call):
            if not grant.collaborate:
                raise PermissionError("collaboration is disabled")
            seen.append((grant.peer_id, call.text))
            return {"text": call.text, "large": "响应" * 40000}

        a = PeerNetworkService(tmp_path / "a", dispatch)
        b = PeerNetworkService(tmp_path / "b", dispatch)
        try:
            await wait_for(lambda: server.started)
            await a.grant(PeerGrant(peer_id=b.identity.peer_id, name="B", collaborate=True))
            await b.grant(PeerGrant(peer_id=a.identity.peer_id, name="A", collaborate=True))
            settings = NetworkSettings(enabled=True, signaling_url=f"ws://127.0.0.1:{port}/connect",
                                       stun_urls=[])
            await a.configure(settings)
            await b.configure(settings)
            await wait_for(lambda: a.enrollment_state == "pending" and b.enrollment_state == "pending")
            assert a.socket is None and b.socket is None
            for endpoint in (a, b):
                admissions.decide(endpoint.identity.peer_id, "approved")
            await wait_for(lambda: a.socket is not None and b.socket is not None)
            # Deterministic initiator also handles simultaneous connect requests.
            await asyncio.gather(a.connect(b.identity.peer_id), b.connect(a.identity.peer_id))
            await wait_for(lambda: a.connections.status(b.identity.peer_id) == "connected"
                           and b.connections.status(a.identity.peer_id) == "connected")
            call = PeerCall(operation="agent_message", text="hello", message_id="msg", graph_id="g", node_id="n",
                            source_graph_id="g2", source_node_id="n2")
            result = await a.call(b.identity.peer_id, call)
            assert result["text"] == "hello" and len(result["large"]) == 80000
            assert (await b.call(a.identity.peer_id, call))["text"] == "hello"
            # Disable the coordinator and prove subsequent business data still flows directly.
            for service in (a, b):
                service.task.cancel()
                await asyncio.gather(service.task, return_exceptions=True)
                service.task = None
            assert a.socket is None and b.socket is None
            assert (await a.call(b.identity.peer_id, call))["text"] == "hello"
            # Permission changes are checked on existing data channels.
            await b.grant(PeerGrant(peer_id=a.identity.peer_id, name="A", collaborate=False))
            with pytest.raises(RuntimeError, match="collaboration is disabled"):
                await a.call(b.identity.peer_id, call)
            await b.revoke(a.identity.peer_id)
            assert a.identity.peer_id not in b.connections.links
            with pytest.raises(PermissionError):
                await b.call(a.identity.peer_id, call)
            assert len(seen) == 3
            await a.configure(NetworkSettings(enabled=False))
            assert a.task is None and a.socket is None and not a.connections.links
        finally:
            await a.stop()
            await b.stop()
            server.should_exit = True
            await asyncio.wait_for(server_task, 10)
            sock.close()

    asyncio.run(scenario())
