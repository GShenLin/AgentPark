import asyncio
import base64
import json
import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from src.peer_network.contracts import BoardHttpRequest, PeerCall, PortalTicket
from src.peer_network.identity import DeviceIdentity, verify
from src.peer_network.service import PeerNetworkService
from src.peer_network.signaling import create_signaling_app
from src.peer_network.enrollment import DeviceAdmissions
from src.web_backend.access_api import AccessApiDomain
from src.web_backend.peer_board_http import PeerBoardHttp, allowed_board_request

TOKEN = "test-device-access-token-" * 3
PASSWORD = "test-portal-admin-password"
BASE = "http://127.0.0.1"


def register_device(ws, identity, name="My PC", portal_board=True):
    challenge = ws.receive_json()["challenge"]
    metadata = {"display_name": name, "portal_board": portal_board, "stun_urls": []}
    ws.send_json({"public_key": identity.public_key, **metadata,
                  "signature": identity.sign({"challenge": challenge, **metadata})})
    return ws.receive_json()


def test_portal_requires_admin_and_lists_only_current_device_connections(tmp_path):
    (tmp_path / "index.html").write_text("<html><head></head><body>App</body></html>", encoding="utf-8")
    admissions = DeviceAdmissions()
    app = create_signaling_app(admissions=admissions, portal_password=PASSWORD, web_root=tmp_path)
    with TestClient(app, base_url=BASE) as client:
        assert 'name="agentpark-portal"' in client.get("/").text
        assert client.get("/portal/api/devices").status_code == 401
        assert client.post("/portal/api/login", json={"password": PASSWORD}).status_code == 403
        response = client.post("/portal/api/login", headers={"origin": BASE}, json={"password": PASSWORD})
        assert response.status_code == 204
        assert "HttpOnly" in response.headers["set-cookie"]
        assert client.get("/portal/api/devices").json()["devices"] == []
        device = DeviceIdentity(Ed25519PrivateKey.generate())
        admissions.request(device.peer_id, "My PC", "127.0.0.1")
        admissions.decide(device.peer_id, "approved")
        with client.websocket_connect("/connect") as ws:
            register_device(ws, device)
            listing = client.get("/portal/api/devices").json()["devices"]
            assert len(listing) == 1 and listing[0]["peer_id"] == device.peer_id
            assert listing[0]["name"] == "My PC" and listing[0]["connected_at"]
            assert TOKEN not in json.dumps(listing)
            assert client.get("/board/" + device.peer_id).status_code == 200
        assert client.get("/portal/api/devices").json()["devices"] == []
        assert client.post("/portal/api/logout", headers={"origin": BASE}).status_code == 204
        assert client.get("/portal/api/devices").status_code == 401


@pytest.mark.parametrize("login_age", [0, 2 * 86400, 3 * 86400 - 120])
def test_portal_browser_offer_gets_a_device_and_session_bound_ticket(monkeypatch, login_age):
    from src.peer_network import portal_auth
    now = time.time()
    monkeypatch.setattr(portal_auth, "time", SimpleNamespace(time=lambda: now - login_age))
    coordinator = DeviceIdentity(Ed25519PrivateKey.generate())
    admissions = DeviceAdmissions()
    app = create_signaling_app(admissions=admissions, portal_password=PASSWORD, signing_identity=coordinator)
    with TestClient(app, base_url=BASE) as client:
        assert client.post("/portal/api/login", headers={"origin": BASE}, json={"password": PASSWORD}).status_code == 204
        monkeypatch.setattr(portal_auth, "time", SimpleNamespace(time=lambda: now))
        assert client.get("/portal/api/devices").status_code == 200
        device, browser = (DeviceIdentity(Ed25519PrivateKey.generate()) for _ in range(2))
        admissions.request(device.peer_id, "My PC", "127.0.0.1")
        admissions.decide(device.peer_id, "approved")
        with client.websocket_connect("/connect") as ws:
            register_device(ws, device)
            with client.websocket_connect("ws://127.0.0.1/portal/connect", headers={"origin": BASE}) as visitor:
                challenge = visitor.receive_json()["challenge"]
                visitor.send_json({"public_key": browser.public_key, "signature": browser.sign({"challenge": challenge})})
                ready = visitor.receive_json()
                assert ready["peer_id"] == browser.peer_id
                visitor.send_json(browser.signal("offer", device.peer_id, "a" * 32, "test-offer"))
                packet = ws.receive_json()
                ticket = PortalTicket.model_validate(packet["ticket"])
                verify(coordinator.public_key, ticket.signature, ticket.model_dump(exclude={"signature"}))
                assert ticket.browser_id == browser.peer_id and ticket.target == device.peer_id
                assert ticket.session_id == "a" * 32 and ticket.expires_at > time.time()
                assert ticket.expires_at - time.time() <= 3600
                assert ticket.expires_at <= int(now - login_age) + 3 * 86400
                assert ready["ice"]["expires_at"] == ticket.expires_at
                ws.send_json(device.signal("answer", browser.peer_id, "a" * 32, "test-answer"))
                assert visitor.receive_json()["signal"]["sdp"] == "test-answer"
                update = dict(kind="ice_candidate", target=device.peer_id, session_id="a" * 32,
                              public_key=browser.public_key, expires_at=int(time.time()) + 60,
                              sequence=0, candidate=None, sdp_mid=None, sdp_mline_index=None)
                visitor.send_json({**update, "signature": browser.sign(update)})
                forwarded = ws.receive_json()
                assert forwarded["signal"]["kind"] == "ice_candidate"
                assert forwarded["ticket"] == packet["ticket"]
            assert ws.receive_json() == {"kind": "portal_close", "peer_id": browser.peer_id}


@pytest.mark.parametrize("path", ["/api/access/settings", "/api/provider-auth/codex/status", "/api/files/read?path=.auth/key", "/api/peers", "/api/settings/model-provider"])
def test_authenticated_board_admin_can_access_management_endpoints(path):
    assert allowed_board_request("GET", path)


def test_board_bridge_uses_asgi_remote_identity_and_never_loopback():
    app = FastAPI()
    @app.get("/api/access/status")
    async def access(request: Request):
        return AccessApiDomain().get_status(request)
    bridge = PeerBoardHttp(SimpleNamespace(), app)
    result = asyncio.run(bridge("b" * 64, BoardHttpRequest(method="GET", path="/api/access/status",
                                                          headers={"x-agentpark-client-id": "local"})))
    body = json.loads(base64.b64decode(result["body"]))
    assert result["status"] == 200 and body["is_developer"] and not body["is_local_client"]
    assert body["client_id"] == "peer:" + "b" * 64


def test_portal_ticket_checks_expiry_target_and_device_setting(tmp_path):
    async def dispatch(*args):
        return {}
    service = PeerNetworkService(tmp_path, dispatch)
    service.board_dispatch = dispatch
    signer, browser = (DeviceIdentity(Ed25519PrivateKey.generate()) for _ in range(2))
    service.coordinator_public_key = signer.public_key
    payload = {"browser_id": browser.peer_id, "target": "f" * 64, "session_id": "a" * 32, "expires_at": int(time.time()) + 60}
    packet = {"ticket": {**payload, "signature": signer.sign(payload)},
              "signal": browser.signal("offer", service.identity.peer_id, "a" * 32, "test-sdp")}
    with pytest.raises(ValueError, match="not bound"):
        asyncio.run(service.accept_portal(packet))
    service.portal_tickets[browser.peer_id] = PortalTicket(**{**payload, "signature": signer.sign(payload)})
    service.store.settings.portal_board = False
    with pytest.raises(PermissionError):
        asyncio.run(service.dispatch_portal(browser.peer_id, PeerCall(operation="board_http", http=BoardHttpRequest(method="GET", path="/api/graphs"))))


def test_board_undo_is_bound_to_the_browser_that_received_the_receipt():
    app = FastAPI()
    @app.delete("/api/nodes/instances/test")
    async def delete():
        return {"undo_token": "test-undo-token"}
    @app.post("/api/undo/test-undo-token")
    async def undo():
        return {"ok": True}
    bridge = PeerBoardHttp(SimpleNamespace(), app)
    async def scenario():
        call = BoardHttpRequest(method="POST", path="/api/undo/test-undo-token")
        assert (await bridge("a" * 64, call))["status"] == 403
        await bridge("a" * 64, BoardHttpRequest(method="DELETE", path="/api/nodes/instances/test"))
        assert (await bridge("b" * 64, call))["status"] == 403
        assert (await bridge("a" * 64, call))["status"] == 200
        assert (await bridge("a" * 64, call))["status"] == 403
    asyncio.run(scenario())


def test_portal_event_stream_hides_private_graphs_and_advances_cursor():
    from src.web_backend.graph_event_stream import GraphEventStreamStore
    events = GraphEventStreamStore()
    def visible(graph, request):
        if graph == "secret":
            raise HTTPException(404)
    core = SimpleNamespace(graph_events=events, default_graph_id="default",
                           graph_api=SimpleNamespace(require_graph_visible=visible,
                               sanitize_graph_event_for_request=lambda graph, event, request: event))
    bridge = PeerBoardHttp(core, FastAPI())
    async def scenario():
        initial = await bridge("a" * 64, BoardHttpRequest(method="GET", path="/api/app/events/stream"))
        assert initial["headers"]["x-peer-event-cursor"] == "0"
        events.publish("secret", {"event": "hidden", "content": "private content"})
        hidden = await bridge("a" * 64, BoardHttpRequest(method="GET", path="/api/app/events/stream", headers={"last-event-id": "0"}))
        assert b"private content" not in base64.b64decode(hidden["body"])
        assert hidden["headers"]["x-peer-event-cursor"] == "1"
        events.publish("default", {"event": "public", "content": "visible content"})
        public = await bridge("a" * 64, BoardHttpRequest(method="GET", path="/api/app/events/stream", headers={"last-event-id": "1"}))
        assert b"visible content" in base64.b64decode(public["body"])
        assert public["headers"]["x-peer-event-cursor"] == "2"
    asyncio.run(scenario())


def test_portal_login_body_is_bounded_and_admin_password_is_separate():
    with TestClient(create_signaling_app(portal_password=PASSWORD), base_url=BASE) as client:
        assert client.post("/portal/api/login", headers={"origin": BASE}, json={"password": TOKEN}).status_code == 401
        assert client.post("/portal/api/login", headers={"origin": BASE}, content="x" * 4097).status_code == 413
