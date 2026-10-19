"""WorkBuddy boundary, credentials, settings API and real curl/SSE integration."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import threading
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.workbuddy.contracts import Catalog, Login
from src.workbuddy.gateway import WorkBuddyGateway, WorkBuddyError, gateway_origin
from src.workbuddy.manager import WorkBuddyServiceManager


MODEL = {"id": "model-1", "name": "Chat", "description": "Test model", "contextWindow": 64000,
         "maxTokens": 4096, "supportsImages": False, "reasoningEfforts": ["high"],
         "billing": {"label": "", "multiplier": None, "free": False,
                     "promotionEndsAt": "", "promotionText": ""}}


@pytest.fixture
def gateway_server(monkeypatch):
    captured = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            pass

        def do_GET(self):
            assert self.headers["Authorization"] == "Bearer test-key"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"data": [MODEL], "token": "do-not-return"}).encode())

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            captured.append(body)
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            if len(captured) == 1:
                deltas = [{"tool_calls": [{"index": 0, "id": "call-1", "type": "function",
                    "function": {"name": "echo_tool", "arguments": '{"message":"hello"}'}}]}]
                finish = "tool_calls"
            else:
                deltas = [{"content": "tool "}, {"content": "worked"}]
                finish = "stop"
            for delta in deltas:
                self.wfile.write(("data: " + json.dumps({"choices": [{"index": 0, "delta": delta,
                    "finish_reason": None}]}) + "\n\n").encode())
            self.wfile.write(("data: " + json.dumps({"choices": [{"index": 0, "delta": {}, "finish_reason": finish}]}) + "\n\ndata: [DONE]\n\n").encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setattr("src.workbuddy.gateway.resolve_provider_api_key", lambda config: "test-key")
    try:
        yield {"type": "workbuddy", "baseUrl": f"http://127.0.0.1:{server.server_port}/v1",
               "apiKey": "test-key", "model": "model-1", "maxRetries": 0}, captured
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


def test_real_curl_stream_tool_round_trip(gateway_server):
    from tests.test_openai_chat_runtime import _build_openai_chat_agent
    from src.providers.workbuddy_agent import WorkBuddyAgent
    config, requests = gateway_server
    agent = _build_openai_chat_agent()
    agent.__class__ = WorkBuddyAgent
    agent.config.update(config)
    calls, chunks = [], []
    def echo_tool(message=None):
        calls.append(message)
        return "echo:" + message
    agent.tools.function_map["echo_tool"] = echo_tool
    agent.tool_declarations = [{"type": "function", "function": {"name": "echo_tool",
        "description": "echo", "parameters": {"type": "object", "properties": {"message": {"type": "string"}}}}}]
    result = agent.Send(stream=True, thinking="enabled", reasoning_effort="high",
                        stream_handler=lambda delta, full: chunks.append(delta))
    assert result == "tool worked"
    assert calls == ["hello"]
    assert "".join(chunks) == "tool worked"
    assert len(requests) == 2
    assert requests[0]["reasoning_effort"] == "high"
    assert requests[0]["max_tokens"] == 4096
    assert "thinking" not in requests[0]
    assert any(m.get("role") == "tool" and m["tool_call_id"] == "call-1" for m in requests[1]["messages"])


def test_catalog_does_not_leak_tokens_and_preserves_unknown_pricing(gateway_server):
    config, _ = gateway_server
    result = WorkBuddyGateway(config).catalog().model_dump()
    assert "token" not in result
    assert result["data"][0]["billing"]["free"] is False
    assert result["data"][0]["billing"]["multiplier"] is None


@pytest.mark.parametrize("url", ["http://external.test/v1", "https://user:pass@host/v1",
                               "https://host/v1?key=secret", "https://host/other"])
def test_reject_unsafe_origins(url):
    with pytest.raises(ValueError):
        gateway_origin(url)


def test_strict_catalog_and_login_contracts():
    with pytest.raises(ValueError):
        Catalog.model_validate({"data": [MODEL, MODEL]})
    with pytest.raises(ValueError):
        Catalog.model_validate({"data": [{**MODEL, "contextWindow": "64000"}]})
    with pytest.raises(ValueError):
        Login.model_validate({"loginId": "a" * 24, "authorizationUrl": "https://evil.test/login"})


def test_http_errors_never_include_upstream_body(gateway_server, monkeypatch):
    config, _ = gateway_server
    gateway = WorkBuddyGateway(config)
    monkeypatch.setattr(gateway.transport, "request", lambda **_: SimpleNamespace(status_code=401, body="secret-token"))
    with pytest.raises(WorkBuddyError, match="HTTP 401") as error:
        gateway.login()
    assert "secret" not in str(error.value)


def test_model_capabilities_fail_before_inference(gateway_server):
    from src.providers.workbuddy_agent import WorkBuddyChatRuntime
    config, requests = gateway_server
    runtime = WorkBuddyChatRuntime(SimpleNamespace(config=config))
    with pytest.raises(WorkBuddyError, match="思考强度"):
        runtime._build_chat_payload(messages=[], active_tools=[], reasoning_effort="max", thinking_mode="enabled", stream=True)
    with pytest.raises(WorkBuddyError, match="图片"):
        runtime._build_chat_payload(messages=[{"role": "user", "content": [{"type": "image_url"}]}],
                                   active_tools=[], reasoning_effort=None, thinking_mode="disabled", stream=True)
    assert requests == []


def test_manager_persists_settings_and_surfaces_install_errors(tmp_path, monkeypatch):
    manager = WorkBuddyServiceManager(tmp_path)
    manager.configure(True, 18990)
    assert WorkBuddyServiceManager(tmp_path).settings == {"autoStart": True, "port": 18990}
    def fail(*_args):
        raise RuntimeError("installer failed")
    monkeypatch.setattr("src.workbuddy.manager.install", fail)
    manager.begin("install")
    manager.worker.join(3)
    assert manager.status()["state"] == "failed"
    assert manager.status()["error"] == "installer failed"
    manager.close()


def test_partial_environment_is_not_reported_as_installed(tmp_path):
    from src.workbuddy.installation import DEPENDENCIES, installed, python_path
    executable = python_path(tmp_path)
    executable.parent.mkdir(parents=True)
    executable.touch()
    assert not installed(tmp_path)
    (tmp_path / "installed.json").write_text(json.dumps({name: revision for name, _, revision in DEPENDENCIES}), encoding="utf-8")
    assert installed(tmp_path)
    (tmp_path / "installed.json").write_text('{"dsh-workbuddy":"outdated"}', encoding="utf-8")
    assert not installed(tmp_path)


def test_startup_uses_only_explicit_autostart_preference(tmp_path, monkeypatch):
    manager = WorkBuddyServiceManager(tmp_path)
    operations = []
    monkeypatch.setattr(manager, "begin", operations.append)
    manager.startup()
    assert operations == []
    manager.configure(True, 18788)
    manager.startup()
    assert operations == ["start"]


def test_manager_rejects_port_change_and_drains_owned_process(tmp_path):
    manager = WorkBuddyServiceManager(tmp_path)
    manager.state = "running"
    with pytest.raises(RuntimeError, match="停止"):
        manager.configure(False, 18800)
    events = []
    process = SimpleNamespace(stdin=SimpleNamespace(close=lambda: events.append("close")),
        wait=lambda timeout: events.append("wait"), poll=lambda: 0)
    manager.process = process
    manager.close()
    assert events == ["close", "wait"]
    assert manager.process is None


def test_settings_api_rejects_extra_input_and_foreign_providers(tmp_path, monkeypatch):
    from src.web_backend.workbuddy_api import WorkBuddyApiDomain
    monkeypatch.setattr("src.web_backend.workbuddy_api.get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr("src.web_backend.workbuddy_api.ConfigLoader.get_provider_config", lambda *_: {"type": "openai"})
    domain = WorkBuddyApiDomain(SimpleNamespace())
    app = FastAPI()
    app.post("/service")(domain.service)
    app.post("/account/{provider_id}")(domain.account)
    with TestClient(app) as client:
        assert client.post("/service", json={"operation": "start", "command": "arbitrary"}).status_code == 422
        assert client.post("/account/test", json={"operation": "login"}).status_code == 409
        assert client.post("/service", json={"operation": "configure", "port": 18888, "autoStart": True}).json()["port"] == 18888
