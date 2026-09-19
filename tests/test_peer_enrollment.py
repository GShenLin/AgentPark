import json
import time

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.websockets import WebSocketDisconnect

from src.peer_network.contracts import DeviceSetup
from src.peer_network.enrollment import DeviceAdmissions
from src.peer_network.identity import DeviceIdentity
from src.peer_network.signaling import create_signaling_app


BASE = "http://127.0.0.1"
PASSWORD = "enrollment-test-password"


def proof(ws, identity, signer=None):
    challenge = ws.receive_json()["challenge"]
    metadata = {"display_name": "My computer", "portal_board": True, "stun_urls": []}
    ws.send_json({"public_key": identity.public_key, **metadata,
                  "signature": (signer or identity).sign({"challenge": challenge, **metadata})})
    return ws.receive_json()


def login(client):
    assert client.post("/portal/api/login", headers={"origin": BASE}, json={"password": PASSWORD}).status_code == 204


def test_ip_only_setup_derives_secure_endpoints_and_rejects_injected_configuration():
    settings = DeviceSetup(enabled=True, server_ip=" 203.0.113.10 ").connection_settings()
    assert settings.signaling_url == "wss://203.0.113.10/connect"
    assert settings.stun_urls == ["stun:203.0.113.10:3478"]
    assert settings.display_name and "access_token" not in settings.model_dump()
    ipv6 = DeviceSetup(enabled=True, server_ip="2001:db8::1").connection_settings()
    assert ipv6.signaling_url == "wss://[2001:db8::1]/connect"
    assert ipv6.stun_urls == ["stun:[2001:db8::1]:3478"]
    for value in ["http://203.0.113.10", "example.com", "203.0.113.10:80", "1.2.3.4/connect", "fe80::1%eth0"]:
        with pytest.raises(ValidationError):
            DeviceSetup(enabled=True, server_ip=value)
    with pytest.raises(ValueError):
        DeviceSetup(enabled=True, server_ip="").connection_settings()
    with pytest.raises(ValidationError):
        DeviceSetup(enabled=True, server_ip="203.0.113.10", access_token="old-token")


def test_pending_device_requires_admin_approval_and_persists_across_restart(tmp_path):
    path = tmp_path / "devices.json"
    admissions = DeviceAdmissions(path)
    identity = DeviceIdentity(Ed25519PrivateKey.generate())
    app = create_signaling_app(admissions=admissions, portal_password=PASSWORD)
    with TestClient(app, base_url=BASE) as client:
        with client.websocket_connect("/connect") as ws:
            assert proof(ws, identity) == {"kind": "enrollment", "state": "pending", "peer_id": identity.peer_id}
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        decision_url = "/portal/api/enrollments/" + identity.peer_id
        assert client.get("/portal/api/enrollments").status_code == 401
        assert client.put(decision_url, headers={"origin": BASE}, json={"state": "approved"}).status_code == 401
        login(client)
        assert client.get("/portal/api/devices").json() == {"devices": []}
        pending = client.get("/portal/api/enrollments").json()["devices"]
        assert len(pending) == 1 and pending[0]["peer_id"] == identity.peer_id
        assert client.put(decision_url, json={"state": "approved"}).status_code == 403
        assert client.put(decision_url, headers={"origin": BASE}, json={"state": "approved", "extra": True}).status_code == 422
        assert client.put(decision_url, headers={"origin": BASE}, json={"state": "approved"}).status_code == 200
    restarted = create_signaling_app(admissions=DeviceAdmissions(path), portal_password=PASSWORD)
    with TestClient(restarted, base_url=BASE) as client:
        login(client)
        with client.websocket_connect("/connect") as ws:
            assert proof(ws, identity)["kind"] == "ready"
            assert client.get("/portal/api/devices").json()["devices"][0]["peer_id"] == identity.peer_id
        assert client.get("/portal/api/devices").json()["devices"] == []
    assert "private_key" not in json.dumps(json.loads(path.read_text()))


def test_rejection_cannot_be_bypassed_and_approved_key_cannot_be_impersonated(tmp_path):
    admissions = DeviceAdmissions(tmp_path / "devices.json")
    identity, attacker = (DeviceIdentity(Ed25519PrivateKey.generate()) for _ in range(2))
    with TestClient(create_signaling_app(admissions=admissions, portal_password=PASSWORD), base_url=BASE) as client:
        with client.websocket_connect("/connect") as ws:
            assert proof(ws, identity)["state"] == "pending"
        login(client)
        url = "/portal/api/enrollments/" + identity.peer_id
        assert client.put(url, headers={"origin": BASE}, json={"state": "rejected"}).status_code == 200
        with client.websocket_connect("/connect", headers={"authorization": "Bearer " + PASSWORD}) as ws:
            assert proof(ws, identity)["state"] == "rejected"
        assert client.put(url, headers={"origin": BASE}, json={"state": "approved"}).status_code == 200
        with client.websocket_connect("/connect") as ws:
            with pytest.raises(WebSocketDisconnect):
                proof(ws, identity, signer=attacker)
        assert client.get("/portal/api/devices").json()["devices"] == []
        with client.websocket_connect("/connect") as ws:
            assert proof(ws, attacker)["state"] == "pending"


def test_enrollment_limits_expiry_and_failed_persistence_do_not_grant_access(tmp_path, monkeypatch):
    admissions = DeviceAdmissions(tmp_path / "devices.json")
    for index in range(10):
        assert admissions.request(f"{index:064x}", "Device", "address") == "pending"
    with pytest.raises(ValueError, match="limit"):
        admissions.request("f" * 64, "Device", "address")
    admissions.records["0" * 64].last_seen = int(time.time()) - 601
    with pytest.raises(KeyError):
        admissions.decide("0" * 64, "approved")
    def fail_save():
        raise OSError("disk full")
    monkeypatch.setattr(admissions, "save", fail_save)
    with pytest.raises(OSError):
        admissions.decide(f"{1:064x}", "approved")
    assert admissions.request(f"{1:064x}", "Device", "address") == "pending"
