import asyncio
import base64
import hashlib
import hmac
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.peer_network.contracts import NetworkSettings
from src.peer_network.enrollment import DeviceAdmissions
from src.peer_network.ice import IceLease, TurnIssuer, TurnServer
from src.peer_network.identity import DeviceIdentity
from src.peer_network.service import PeerNetworkService
from src.peer_network.signaling import create_signaling_app


URLS = ("turn:relay.example.com:3478?transport=tcp", "turn:relay.example.com:3478?transport=udp")
SECRET = "test-only-shared-key-" * 3
BASE = "http://127.0.0.1"


def test_turn_credentials_are_time_bound_and_compatible_with_coturn(monkeypatch):
    monkeypatch.setattr(time, "time", lambda: 1000)
    issuer = TurnIssuer(URLS, SECRET)
    lease = issuer.issue("a" * 64)
    server = lease.ice_servers[0]
    assert lease.expires_at == 4600
    assert server.username == "4600:" + "a" * 64
    assert server.credential == base64.b64encode(hmac.new(SECRET.encode(), server.username.encode(), hashlib.sha1).digest()).decode()
    assert issuer.issue("b" * 64).ice_servers[0].credential != server.credential
    assert issuer.issue("a" * 64, expires_at=1100).expires_at == 1100
    assert SECRET not in repr(issuer)
    assert server.credential not in repr(lease)
    assert TurnIssuer().issue("a" * 64).ice_servers == []
    monkeypatch.setattr(time, "time", lambda: 4600)
    with pytest.raises(ValueError, match="expired"):
        lease.require_fresh()


@pytest.mark.parametrize("url", ["https://relay.example.com", "turn:user:password@host:3478?transport=tcp",
                                     "turns:host:5349?transport=udp", "turn:host:99999?transport=tcp"])
def test_turn_rejects_invalid_config_without_exposing_credentials(url):
    with pytest.raises(ValueError):
        TurnIssuer((url,), SECRET)
    with pytest.raises(ValidationError) as error:
        TurnServer(urls=[url], username="user", credential="private-credential")
    assert "private-credential" not in str(error.value)


def test_turn_requires_both_server_urls_and_secret():
    with pytest.raises(ValueError):
        TurnIssuer(URLS)
    with pytest.raises(ValueError):
        TurnIssuer(secret=SECRET)
    with pytest.raises(ValueError):
        TurnIssuer(URLS, "short")


def register(ws, identity):
    challenge = ws.receive_json()["challenge"]
    metadata = {"display_name": "TURN test", "portal_board": True, "stun_urls": []}
    ws.send_json({"public_key": identity.public_key, **metadata,
                  "signature": identity.sign({"challenge": challenge, **metadata})})
    return ws.receive_json()


def test_only_approved_devices_and_authenticated_browsers_get_relay_credentials():
    admissions = DeviceAdmissions()
    issuer = TurnIssuer(URLS, SECRET)
    app = create_signaling_app(admissions=admissions, portal_password="test-admin-password", turn=issuer)
    device, browser = (DeviceIdentity(Ed25519PrivateKey.generate()) for _ in range(2))
    with TestClient(app, base_url=BASE) as client:
        assert client.get("/portal/api/devices").status_code == 401
        with client.websocket_connect("/connect") as ws:
            pending = register(ws, device)
            assert pending["kind"] == "enrollment" and "ice" not in pending
        admissions.decide(device.peer_id, "approved")
        with client.websocket_connect("/connect") as ws:
            lease = IceLease.model_validate(register(ws, device)["ice"])
            lease.require_fresh()
            assert lease.ice_servers[0].username.endswith(device.peer_id)
            ws.send_json({"kind": "ice_refresh"})
            assert ws.receive_json()["kind"] == "ice"
            client.post("/portal/api/login", headers={"origin": BASE}, json={"password": "test-admin-password"})
            listing = client.get("/portal/api/devices").text
            assert SECRET not in listing and "credential" not in listing
            with client.websocket_connect("ws://127.0.0.1/portal/connect", headers={"origin": BASE}) as visitor:
                challenge = visitor.receive_json()["challenge"]
                visitor.send_json({"public_key": browser.public_key, "signature": browser.sign({"challenge": challenge})})
                reply = visitor.receive_json()
                browser_lease = IceLease.model_validate(reply["ice"])
                assert browser_lease.ice_servers[0].username.endswith(browser.peer_id)
                assert SECRET not in str(reply)


def test_backend_uses_issued_turn_and_never_saves_credentials(tmp_path):
    pytest.importorskip("aiortc")
    async def dispatch(*args):
        return {}
    service = PeerNetworkService(tmp_path, dispatch)
    service.store.settings = NetworkSettings(stun_urls=[])
    service.ice_lease = TurnIssuer(URLS, SECRET).issue(service.identity.peer_id)
    service.store.save()
    saved = (tmp_path / "network.json").read_text()
    assert "credential" not in saved and SECRET not in saved
    async def scenario():
        link = await service.connections.new("a" * 64, "b" * 32)
        channel = link.pc.createDataChannel("test")
        # Inspect aiortc's configured transport without making external requests.
        transport = link.pc.sctp.transport.transport
        assert transport._connection.turn_server == ("relay.example.com", 3478)
        assert transport._connection.turn_transport == "tcp"
        channel.close()
        await service.connections.close()
        service.ice_lease.expires_at = 1
        with pytest.raises(ValueError, match="expired"):
            await service.connections.new("a" * 64, "c" * 32)
    asyncio.run(scenario())
