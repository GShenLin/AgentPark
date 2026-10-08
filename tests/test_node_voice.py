import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from src.providers.openai_realtime_voice import OpenAIRealtimeVoiceProvider
from src.providers.voice_provider import VoiceCall
from src.providers.curl_types import CurlResponse
from src.voice_settings import VoiceSettings
from src.web_backend.node_voice import NodeVoiceApi, VoiceDelegation, VoiceLease


@pytest.fixture
def voice(monkeypatch, tmp_path):
    config = {"pending": [], "inflight": None}
    core = SimpleNamespace(
        access_api=SimpleNamespace(message_access_metadata=lambda request: {"_access_client_id": request}),
        node_ops=SimpleNamespace(require_node_visible=Mock(), enqueue_node_instance_pending=Mock()),
        graph_runtime=SimpleNamespace(_sanitize_graph_id=lambda value: value or "default",
                                      _node_config_path=lambda *_: "node-config",
                                      _node_messages_path=lambda *_: str(tmp_path / "messages.jsonl")),
        node_live_outputs=SimpleNamespace(get=lambda *_: {}),
    )
    monkeypatch.setattr("src.web_backend.node_voice.node_config_service.read_strict", lambda _: config)
    service = NodeVoiceApi(core)
    service._leases["session"] = VoiceLease("node", "default", "owner", time.monotonic() + 60)
    service._receipts.register("node", "default", "session", "owner", service._leases["session"].started_at)
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


def test_rtc_control_is_typed_and_bound_to_original_node_and_owner(voice, monkeypatch):
    from src.providers.voice_provider import RtcVoiceCall
    service, _, _ = voice
    session = SimpleNamespace(control=AsyncMock())
    service._leases["session"].call = RtcVoiceCall("app", "room", "user", "bot", "scoped-token", "model", session)
    monkeypatch.setattr(service, "_owner", lambda request: request.headers.get("x-test-owner", "owner"))
    app = FastAPI(); app.post("/voice/{node_id}/{session_id}/control")(service.control)
    with TestClient(app) as client:
        assert client.post("/voice/node/session/control", json={"action": "activate"}).status_code == 200
        assert client.post("/voice/node/session/control", json={"action": "screen", "enabled": True, "fps": 30}).status_code == 200
        assert client.post("/voice/node/session/control", json={"action": "screen", "enabled": True, "fps": 31}).status_code == 422
        assert client.post("/voice/other/session/control", json={"action": "activate"}).status_code == 404
        assert client.post("/voice/node/session/control", json={"action": "activate"}, headers={"x-test-owner": "stranger"}).status_code == 404
    assert session.control.await_count == 2


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


def test_voice_progress_is_request_scoped_public_activity_only(voice):
    service, core, config = voice
    service._leases["session"].tasks["d"] = ("task", "work")
    config["pending"] = [{"trace_id": "task"}]
    live = {"trace_id": "other", "thinking_text": "private reasoning",
            "activity_blocks": [{"id": "c1", "type": "tool_call", "status": "running", "label": "read_file",
                                 "arguments": {"secret": "do not speak"}}]}
    core.node_live_outputs.get = lambda *_: live
    assert service.task("node", "session", "task", "owner") == {"status": "queued", "text": ""}
    live["trace_id"] = "task"
    assert service.task("node", "session", "task", "owner") == {"status": "running", "text": "正在读取文件"}


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
    monkeypatch.setattr(service, "_context", lambda *_: ({}, "node context", VoiceSettings()))
    async def create(config, sdp, context, settings, **kwargs):
        assert sdp.startswith("v=0") and context == "node context"
        return VoiceCall("v=0\r\nm=audio 9 test\r\n", "gpt-realtime-2.1", "openai-realtime-v1")
    monkeypatch.setattr("src.web_backend.node_voice.voice_provider", lambda _: SimpleNamespace(
        transport="webrtc", protocol="openai-realtime-v1", validate=lambda _: None, server_media=False, delegation=True, node_owned_dialogue=True, create_call=create))
    app = FastAPI()
    app.post("/voice/{node_id}")(service.start)
    client = TestClient(app)
    assert client.post("/voice/node", json={"sdp": "invalid"}).status_code == 422
    result = client.post("/voice/node", json={"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n", "protocols": ["openai-realtime-v1"]})
    assert result.status_code == 200
    assert set(result.json()) == {"transport", "sdp", "session_id", "model", "protocol"}


def test_realtime_call_uses_existing_auth_and_ga_multipart_contract(monkeypatch):
    monkeypatch.setattr("src.providers.openai_realtime_voice.resolve_provider_request_credentials", lambda _: SimpleNamespace(
        base_url="https://chatgpt.com/backend-api/codex", headers={"Authorization": "Bearer private", "ChatGPT-Account-ID": "account"}))
    requests = []
    async def request(_self, **kwargs):
        requests.append(kwargs)
        return CurlResponse("v=0\r\nm=audio 9 test\r\n", 201)
    monkeypatch.setattr("src.providers.openai_realtime_voice.CurlHttpTransport.request_async", request)
    result = asyncio.run(OpenAIRealtimeVoiceProvider().create_call({"type": "openai", "authMode": "codex"}, "offer", "context", VoiceSettings()))
    assert result.model == "gpt-realtime-2.1"
    req = requests[0]
    assert req["url"] == "https://api.openai.com/v1/realtime/calls"
    assert "openai-alpha" not in req["headers"]
    assert req["headers"]["Authorization"] == "Bearer private"
    assert req["headers"]["Content-Type"].startswith("multipart/form-data; boundary=")
    session = json.loads(req["body"].decode("utf-8").split('Content-Type: application/json\r\n\r\n', 1)[1].split("\r\n--", 1)[0])
    assert session["type"] == "realtime"
    assert session["tools"][0]["name"] == "delegate_to_node"
    assert session["audio"]["output"]["voice"] == "marin"
    assert session["audio"]["input"]["turn_detection"]["interrupt_response"] is True
    assert "private" not in repr(result)


@pytest.mark.parametrize("protocols", [None, [], ["openai-realtime-v1"]])
def test_stale_page_is_rejected_before_opening_media_or_charging_provider(voice, monkeypatch, protocols):
    service, _, _ = voice
    provider = SimpleNamespace(protocol="agentpark-voice-v4", validate=Mock(), create_call=AsyncMock())
    monkeypatch.setattr(service, "_owner", lambda _: "owner")
    monkeypatch.setattr(service, "_context", lambda *_: ({}, "context", VoiceSettings()))
    monkeypatch.setattr("src.web_backend.node_voice.voice_provider", lambda _: provider)
    app = FastAPI()
    app.post("/voice/{node_id}")(service.start)
    body = {"sdp": "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"}
    if protocols is not None:
        body["protocols"] = protocols
    result = TestClient(app).post("/voice/node", json=body)
    assert result.status_code == 409
    assert "刷新当前页面" in result.json()["detail"]
    provider.create_call.assert_not_called()


def test_voice_passes_node_context_without_extra_conference_instructions(voice, monkeypatch):
    service, _, _ = voice
    monkeypatch.setattr(service, "_owner", lambda _: "owner")
    monkeypatch.setattr(service, "_context", lambda *_: ({}, "节点：Alice", VoiceSettings()))
    contexts = []
    async def create(config, sdp, context, settings, **kwargs):
        contexts.append(context)
        return VoiceCall("v=0\r\nm=audio 9 test\r\n", "gpt-realtime-2.1", "openai-realtime-v1")
    monkeypatch.setattr("src.web_backend.node_voice.voice_provider", lambda _: SimpleNamespace(
        transport="webrtc", protocol="openai-realtime-v1", validate=lambda _: None, server_media=False, delegation=True, node_owned_dialogue=True, create_call=create))
    app = FastAPI()
    app.post("/voice/{node_id}")(service.start)
    client = TestClient(app)
    sdp = "v=0\r\nm=audio 9 UDP/TLS/RTP/SAVPF 111\r\n"
    assert client.post("/voice/node", json={"sdp": sdp, "protocols": ["openai-realtime-v1"]}).status_code == 200
    assert contexts[0] == "节点：Alice"
    assert client.post("/voice/node", json={"sdp": sdp, "conference": "true"}).status_code == 422
    assert client.post("/voice/node", json={"sdp": sdp, "protocols": ["openai-realtime-v1"]}).status_code == 200
    assert contexts[1] == "节点：Alice"


def test_codex_call_preserves_denial_without_falling_back(monkeypatch):
    monkeypatch.setattr("src.providers.openai_realtime_voice.resolve_provider_request_credentials", lambda _: SimpleNamespace(
        base_url="https://chatgpt.com/backend-api/codex", headers={"Authorization": "Bearer private"}))
    async def request(*_, **kwargs):
        return CurlResponse(json.dumps({"error": {"message": "Voice session access denied."}}), 403)
    monkeypatch.setattr("src.providers.openai_realtime_voice.CurlHttpTransport.request_async", request)
    with pytest.raises(ValueError, match="HTTP 403.*Voice session access denied"):
        asyncio.run(OpenAIRealtimeVoiceProvider().create_call({"type": "openai", "authMode": "codex"}, "offer", "", VoiceSettings()))
    with pytest.raises(ValueError, match="OpenAI"):
        asyncio.run(OpenAIRealtimeVoiceProvider().create_call({"type": "openai", "authMode": "api_key"}, "offer", "", VoiceSettings()))


def test_server_updates_read_only_owned_node_state(voice, monkeypatch):
    service, _, config = voice
    session = SimpleNamespace(deliver_update=AsyncMock(return_value="accepted"))
    service._leases["session"].call = VoiceCall("sdp", "doubao", "agentpark-voice-v4", session)
    service._leases["session"].tasks["q1"] = ("task1", "读取文件")
    config["pending"] = [{"trace_id": "task1"}]
    accepted = asyncio.run(service.deliver_update("node", "session", "task1", "owner"))
    assert accepted == {"status": "queued", "text": "", "delivery": "accepted"}
    assert session.deliver_update.call_args.args[1].status == "queued"
    assert session.deliver_update.call_args.args[1].task_id == "task1"
    config["completed_requests"] = [{"request_id": "task1", "role": "assistant", "message": "真实文件内容"}]
    for node, owner, task in [("other", "owner", "task1"), ("node", "intruder", "task1"), ("node", "owner", "other")]:
        with pytest.raises(HTTPException) as error:
            asyncio.run(service.deliver_update(node, "session", task, owner))
        assert error.value.status_code == 404
    monkeypatch.setattr(service, "_owner", lambda _: "owner")
    app = FastAPI()
    app.post("/voice/{node_id}/{session_id}/{request_id}/updates")(service.deliver_update)
    result = TestClient(app).post("/voice/node/session/task1/updates", json={"text": "伪造完成结果"})
    assert result.json() == {"status": "completed", "text": "真实文件内容", "delivery": "accepted"}
    assert session.deliver_update.call_args.args[0] == "q1"
    assert session.deliver_update.call_args.args[1].text == "真实文件内容"
