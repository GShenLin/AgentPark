import json
import time
from types import SimpleNamespace

import pytest
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.peer_network.contracts import NetworkSettings, PeerCall, PeerGrant, Signal
from src.peer_network.delivery import DeliveryJournal
from src.peer_network.identity import DeviceIdentity, verify_signal
from src.peer_network.principal import PeerPrincipal
from src.peer_network.signaling import create_signaling_app
from src.peer_network.enrollment import DeviceAdmissions
from src.web_backend.access_api import AccessApiDomain
from src.web_backend.peer_api import PeerApiDomain


def test_identity_persists_and_sdp_signature_is_bound_to_peer_and_session(tmp_path):
    identity = DeviceIdentity.load(tmp_path / "identity.json")
    assert DeviceIdentity.load(tmp_path / "identity.json").peer_id == identity.peer_id
    other = DeviceIdentity(Ed25519PrivateKey.generate())
    body = identity.signal("offer", other.peer_id, "a" * 32, "test-sdp")
    assert verify_signal(Signal.model_validate(body), other.peer_id) == identity.peer_id
    with pytest.raises(ValueError):
        verify_signal(Signal.model_validate(body), identity.peer_id)
    body["sdp"] = "changed-dtls-fingerprint"
    with pytest.raises(InvalidSignature):
        verify_signal(Signal.model_validate(body), other.peer_id)
    body["expires_at"] = int(time.time()) - 1
    with pytest.raises(ValueError):
        verify_signal(Signal.model_validate(body), other.peer_id)


def test_contracts_reject_turn_in_stun_list_arbitrary_operations_and_unencrypted_cloud():
    for url in ("ws://example.com/connect", "https://example.com", "wss://user:password@example.com/connect"):
        with pytest.raises(ValidationError):
            NetworkSettings(signaling_url=url)
    with pytest.raises(ValidationError):
        NetworkSettings(stun_urls=["turn:example.com:3478"])
    with pytest.raises(ValidationError):
        PeerCall(operation="http", path="/api/access/settings")
    with pytest.raises(ValidationError):
        PeerGrant(peer_id="a" * 64, name="a", view="true")


def test_signal_clock_skew_is_bounded_and_expiry_is_not_extended(monkeypatch):
    from src.peer_network import identity as identity_module
    identity = DeviceIdentity(Ed25519PrivateKey.generate())
    monkeypatch.setattr(identity_module.time, "time", lambda: 1000.0)
    signal = Signal.model_validate(identity.signal("offer", "a" * 64, "b" * 32, "test"))
    # Observed deployment: Windows is about 0.75 seconds ahead of ECS.
    monkeypatch.setattr(identity_module.time, "time", lambda: 999.25)
    assert verify_signal(signal, "a" * 64) == identity.peer_id
    monkeypatch.setattr(identity_module.time, "time", lambda: 994.9)
    with pytest.raises(ValueError):
        verify_signal(signal, "a" * 64)
    monkeypatch.setattr(identity_module.time, "time", lambda: 1120.0)
    with pytest.raises(ValueError):
        verify_signal(signal, "a" * 64)


def test_delivery_receipt_survives_restart_and_rejects_id_reuse(tmp_path):
    calls = []
    def enqueue():
        calls.append(1)
        return {"queued": True, "completed": False, "duplicate": False}
    journal = DeliveryJournal(tmp_path / "receipts.db")
    assert journal.accept("id", {"text": "hello"}, enqueue)["queued"]
    restarted = DeliveryJournal(tmp_path / "receipts.db")
    assert restarted.accept("id", {"text": "hello"}, enqueue)["duplicate"]
    assert calls == [1]
    with pytest.raises(ValueError, match="different content"):
        restarted.accept("id", {"text": "changed"}, enqueue)


def test_uncertain_delivery_is_not_replayed(tmp_path):
    journal = DeliveryJournal(tmp_path / "receipts.db")
    def crash():
        raise RuntimeError("simulated crash after queue write")
    with pytest.raises(RuntimeError, match="simulated crash"):
        journal.accept("id", {"text": "hello"}, crash)
    with pytest.raises(RuntimeError, match="unknown"):
        journal.accept("id", {"text": "hello"}, lambda: pytest.fail("must not replay"))


def test_peer_identity_never_becomes_local_developer():
    request = Request({"type": "http", "headers": [], "client": ("peer:abc", 0),
                       "state": {"peer_principal": PeerPrincipal("abc", "other")}})
    status = AccessApiDomain().get_status(request)
    assert status["client_id"] == "peer:abc"
    assert not status["is_developer"]
    assert not status["is_local_client"]
    assert AccessApiDomain().message_access_metadata(request)["_access_role"] == "nondeveloper"


def test_peer_management_rejects_remote_clients_and_cross_origin_requests():
    api = PeerApiDomain(SimpleNamespace())
    app = FastAPI()
    app.get("/api/peers")(api.get_status)
    assert TestClient(app, client=("10.1.1.1", 100)).get("/api/peers").status_code == 403
    assert TestClient(app, client=("127.0.0.1", 100)).get(
        "/api/peers", headers={"origin": "https://untrusted.example"}
    ).status_code == 403


def test_coordinator_authenticates_proof_and_never_accepts_business_packets():
    from starlette.websockets import WebSocketDisconnect
    admissions = DeviceAdmissions()
    client = TestClient(create_signaling_app(admissions=admissions))
    identity = DeviceIdentity(Ed25519PrivateKey.generate())
    admissions.request(identity.peer_id, "Test device", "127.0.0.1")
    admissions.decide(identity.peer_id, "approved")
    with client.websocket_connect("/connect") as ws:
        challenge = ws.receive_json()
        metadata = {"display_name": "Test device", "portal_board": True, "stun_urls": []}
        ws.send_json({"public_key": identity.public_key, **metadata,
                      "signature": identity.sign({"challenge": challenge["challenge"], **metadata})})
        ready = ws.receive_json()
        assert ready["kind"] == "ready" and ready["peer_id"] == identity.peer_id
        assert ready["coordinator_public_key"]
        ws.send_json({"kind": "request", "call": {"operation": "message", "text": "cannot relay this"}})
        with pytest.raises(WebSocketDisconnect):
            ws.receive_json()
