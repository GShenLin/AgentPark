import time
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.peer_network import portal_auth, portal_routes
from src.peer_network.identity import DeviceIdentity
from src.peer_network.portal_auth import COOKIE, PortalAuth, SESSION_SECONDS
from src.peer_network.signaling import create_signaling_app


def test_session_lasts_exactly_three_days_without_sliding_expiration(monkeypatch):
    now = 2_000_000_000
    monkeypatch.setattr(portal_auth, "time", SimpleNamespace(time=lambda: now))
    auth = PortalAuth("test1234")
    token = auth.login("test1234", "address")
    request = SimpleNamespace(cookies={COOKIE: token})
    expiry = now + 3 * 86400
    assert SESSION_SECONDS == 259200
    assert auth.require_session(request).expires_at == expiry
    now = expiry - 1
    assert auth.require_session(request).expires_at == expiry
    now = expiry
    with pytest.raises(HTTPException) as caught:
        auth.require_session(request)
    assert caught.value.status_code == 401


def test_login_cookie_is_persistent_for_three_days_and_logout_revokes_it():
    with TestClient(create_signaling_app(portal_password="test1234"), base_url="https://portal.example") as client:
        headers = {"origin": "https://portal.example"}
        response = client.post("/portal/api/login", headers=headers, json={"password": "test1234"})
        assert response.status_code == 204
        cookie = response.headers["set-cookie"]
        for attribute in ("Max-Age=259200", "HttpOnly", "Secure", "SameSite=strict", "Path=/"):
            assert attribute in cookie
        token = client.cookies.get(COOKIE)
        assert client.get("/portal/api/devices").status_code == 200
        assert client.post("/portal/api/logout", headers=headers).status_code == 204
        assert client.get("/portal/api/devices", headers={"cookie": f"{COOKIE}={token}"}).status_code == 401


def test_expired_board_connection_closes_but_login_still_allows_reconnect(monkeypatch):
    now = time.time()
    clock = SimpleNamespace(time=lambda: now)
    monkeypatch.setattr(portal_routes, "time", clock)
    with TestClient(create_signaling_app(portal_password="test1234"), base_url="http://127.0.0.1") as client:
        headers = {"origin": "http://127.0.0.1"}
        assert client.post("/portal/api/login", headers=headers, json={"password": "test1234"}).status_code == 204
        browser = DeviceIdentity(Ed25519PrivateKey.generate())
        with client.websocket_connect("ws://127.0.0.1/portal/connect", headers=headers) as visitor:
            challenge = visitor.receive_json()["challenge"]
            visitor.send_json({"public_key": browser.public_key, "signature": browser.sign({"challenge": challenge})})
            ready = visitor.receive_json()
            now += 3601
            # Wake the receive loop with a valid offer to an offline device.
            visitor.send_json(browser.signal("offer", "f" * 64, "a" * 32, "test-sdp"))
            assert visitor.receive_json()["kind"] == "error"
            with pytest.raises(WebSocketDisconnect):
                visitor.receive_json()
        assert client.get("/portal/api/devices").status_code == 200
        clock.time = time.time
        with client.websocket_connect("ws://127.0.0.1/portal/connect", headers=headers) as visitor:
            challenge = visitor.receive_json()["challenge"]
            visitor.send_json({"public_key": browser.public_key, "signature": browser.sign({"challenge": challenge})})
            assert visitor.receive_json()["kind"] == "ready"
        assert ready["ice"]["expires_at"] <= int(time.time()) + 3600
