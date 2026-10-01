import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.providers.codex_voice import VoiceCallAnswer, create_codex_voice_call
from src.providers.curl_types import CurlResponse
from src.web_backend.node_voice import NodeVoiceApi, VoiceDelegation, VoiceLease


@pytest.fixture
def voice(monkeypatch):
    config = {"pending": [], "inflight": None}
    core = SimpleNamespace(
        access_api=SimpleNamespace(message_access_metadata=lambda request: {"_access_client_id": request}),
        node_ops=SimpleNamespace(require_node_visible=Mock(), enqueue_node_instance_pending=Mock()),
        graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda value: value or "default",
                                      _node_config_path=lambda *_: "node-config"),
        node_live_outputs=SimpleNamespace(get=lambda *_: {}),
    )
    monkeypatch.setattr("src.web_backend.node_voice.node_config_service.read_strict", lambda _: config)
    service = NodeVoiceApi(core)
    service._leases["session"] = VoiceLease("node", "default", "owner", time.monotonic() + 60)
    return service, core, config


def test_delegation_is_exactly_once_and_owned_by_node(voice):
    service, core, _ = voice
    payload = VoiceDelegation(delegation_id="d1", text="读取日志")
    first = service.delegate("node", "session", payload, "owner")
    second = service.delegate("node", "session", payload, "owner")
    assert first["request_id"] == second["request_id"]
    assert second["duplicate"] is True
    core.node_ops.enqueue_node_instance_pending.assert_called_once()
    args = core.node_ops.enqueue_node_instance_pending.call_args.args
    assert args[1]["trace_id"] == first["request_id"]
    assert args[1]["source"] == "voice_call"
    assert args[3] == "owner"
    with pytest.raises(HTTPException) as exc:
        service.delegate("node", "session", VoiceDelegation(delegation_id="d1", text="删除日志"), "owner")
    assert exc.value.status_code == 409


@pytest.mark.parametrize("node,graph,owner", [("other", "default", "owner"), ("node", "other", "owner"), ("node", "default", "intruder")])
def test_session_cannot_be_used_by_another_node_graph_or_client(voice, node, graph, owner):
    service, core, _ = voice
    with pytest.raises(HTTPException) as exc:
        service.delegate(node, "session", VoiceDelegation(delegation_id="d", text="work"), owner, graph)
    assert exc.value.status_code == 404
    core.node_ops.enqueue_node_instance_pending.assert_not_called()


def test_private_node_visibility_is_rechecked(voice):
    service, core, _ = voice
    core.node_ops.require_node_visible.side_effect = HTTPException(404, "private")
    with pytest.raises(HTTPException):
        service.end("node", "session", "owner")


def test_completion_matches_request_and_is_retained(voice):
    service, _, config = voice
    service._leases["session"].tasks["d"] = ("requested", "work")
    config.update(pending=[{"trace_id": "requested"}], completed_requests=[{
        "request_id": "other", "role": "assistant", "message": "wrong result",
    }])
    assert service.task("node", "session", "requested", "owner")["status"] == "queued"
    config["completed_requests"].append({"request_id": "requested", "role": "assistant", "message": "right result"})
    result = service.task("node", "session", "requested", "owner")
    assert result == {"status": "completed", "text": "right result"}
    config["completed_requests"] = []
    assert service.task("node", "session", "requested", "owner") == result


def test_running_failed_and_cancelled_are_not_reported_as_success(voice):
    service, core, config = voice
    service._leases["session"].tasks["d"] = ("task", "work")
    core.node_live_outputs.get = lambda *_: {"trace_id": "task"}
    assert service.task("node", "session", "task", "owner")["status"] == "running"
    core.node_live_outputs.get = lambda *_: {}
    assert service.task("node", "session", "task", "owner")["status"] == "cancelled"
    config["completed_requests"] = [{"request_id": "task", "role": "system", "message": "Error: failed"}]
    assert service.task("node", "session", "task", "owner")["status"] == "failed"


def test_end_and_expiration_reject_new_tasks_without_stopping_node(voice):
    service, core, _ = voice
    service.end("node", "session", "owner")
    with pytest.raises(HTTPException):
        service.delegate("node", "session", VoiceDelegation(delegation_id="d", text="work"), "owner")
    service._leases["expired"] = VoiceLease("node", "default", "owner", time.monotonic() - 1)
    with pytest.raises(HTTPException):
        service.end("node", "expired", "owner")
    core.node_ops.enqueue_node_instance_pending.assert_not_called()


def test_offer_endpoint_has_typed_body_and_keeps_credentials_server_side(voice, monkeypatch):
    service, _, _ = voice
    monkeypatch.setattr(service, "_owner", lambda _: "owner")
    monkeypatch.setattr(service, "_context", lambda *_: ({}, "node context"))
    async def create(config, sdp, context):
        assert sdp.startswith("v=0") and context == "node context"
        return VoiceCallAnswer("v=0\r\nm=audio 9 test\r\n")
    monkeypatch.setattr("src.web_backend.node_voice.create_codex_voice_call", create)
    app = FastAPI()
    app.post("/voice/{node_id}")(service.start)
    client = TestClient(app)
    assert client.post("/voice/node", json={"sdp": "invalid"}).status_code == 422
    result = client.post("/voice/node", json={"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"})
    assert result.status_code == 200
    assert set(result.json()) == {"sdp", "session_id", "model"}


def test_codex_call_uses_existing_auth_and_exact_v3_contract(monkeypatch):
    monkeypatch.setattr("src.providers.codex_voice.resolve_provider_request_credentials", lambda _: SimpleNamespace(
        base_url="https://chatgpt.com/backend-api/codex", headers={"Authorization": "Bearer private", "ChatGPT-Account-ID": "account"}))
    requests = []
    async def request(_self, **kwargs):
        requests.append(kwargs)
        return CurlResponse("v=0\r\nm=audio 9 test\r\n", 201)
    monkeypatch.setattr("src.providers.codex_voice.CurlHttpTransport.request_async", request)
    result = asyncio.run(create_codex_voice_call({"type": "openai", "authMode": "codex"}, "offer", "context"))
    assert result.model == "gpt-live-1-codex"
    req = requests[0]
    assert req["url"].endswith("/realtime/calls?intent=quicksilver&architecture=avas")
    assert req["headers"]["openai-alpha"] == "quicksilver=v2"
    assert req["headers"]["Authorization"] == "Bearer private"
    body = json.loads(req["body"])
    assert body["session"]["delegation"] == {"type": "client"}
    # Regression: V3 uses Codex's V1 voice catalog. The API V2 default marin
    # produces HTTP 201 followed by a misleading forbidden event on the channel.
    assert body["session"]["audio"]["output"]["voice"] == "cove"
    assert "private" not in repr(result)


def test_conference_keeps_node_identity_and_enables_independent_participation(voice, monkeypatch):
    service, _, _ = voice
    monkeypatch.setattr(service, "_owner", lambda _: "owner")
    monkeypatch.setattr(service, "_context", lambda *_: ({}, "节点：Alice"))
    contexts = []
    async def create(config, sdp, context):
        contexts.append(context)
        return VoiceCallAnswer("v=0\r\nm=audio 9 test\r\n")
    monkeypatch.setattr("src.web_backend.node_voice.create_codex_voice_call", create)
    app = FastAPI()
    app.post("/voice/{node_id}")(service.start)
    client = TestClient(app)
    sdp = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    assert client.post("/voice/node", json={"sdp": sdp, "conference": True}).status_code == 200
    assert "节点：Alice" in contexts[0] and "多人语音" in contexts[0]
    assert "自行" in contexts[0] or "自己的判断" in contexts[0]
    assert client.post("/voice/node", json={"sdp": sdp, "conference": "true"}).status_code == 422
    assert client.post("/voice/node", json={"sdp": sdp}).status_code == 200
    assert contexts[1] == "节点：Alice"


def test_codex_call_preserves_denial_without_falling_back(monkeypatch):
    monkeypatch.setattr("src.providers.codex_voice.resolve_provider_request_credentials", lambda _: SimpleNamespace(
        base_url="https://chatgpt.com/backend-api/codex", headers={"Authorization": "Bearer private"}))
    async def request(*_, **kwargs):
        return CurlResponse(json.dumps({"error": {"message": "Voice session access denied."}}), 403)
    monkeypatch.setattr("src.providers.codex_voice.CurlHttpTransport.request_async", request)
    with pytest.raises(ValueError, match="HTTP 403.*Voice session access denied"):
        asyncio.run(create_codex_voice_call({"type": "openai", "authMode": "codex"}, "offer", ""))
    with pytest.raises(ValueError, match="GPT_Official"):
        asyncio.run(create_codex_voice_call({"type": "openai", "authMode": "api_key"}, "offer", ""))
