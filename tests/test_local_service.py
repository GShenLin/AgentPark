"""Exercise custom services through the real API, subprocesses and curl transport."""

import json
import socket
import sys
import time
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.local_model.catalog import Catalog
from src.local_model.contracts import ServiceConfig
from src.local_model.http import LocalHttp
from src.local_model.runtime import LocalModelService
from src.web_backend.local_model_api import register_local_model_routes


@pytest.fixture
def custom_service(tmp_path):
    root = tmp_path / "service with spaces"
    root.mkdir()
    script = root / "server.py"
    script.write_text('''import json, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
Path("received.json").write_text(json.dumps(sys.argv[2:]), encoding="utf-8")
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200 if self.path == "/ready" else 503)
        self.end_headers()
        self.wfile.write(b"<html>ready</html>")
HTTPServer(("127.0.0.1", int(sys.argv[1])), Handler).serve_forever()
''', encoding="utf-8")
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return ServiceConfig(name="Custom service", install_path=str(root), executable=sys.executable,
                         endpoint=f"http://127.0.0.1:{port}", health_path="/ready", startup_timeout=10,
                         extra_args=[str(script), str(port), "argument with spaces", "中文路径"])


def wait_job(client, job):
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        result = client.get("/api/local-model/jobs/" + job["id"])
        assert result.status_code == 200
        value = result.json()
        if value["state"] != "running":
            return value
        time.sleep(.05)
    pytest.fail("service operation did not finish")


def test_custom_service_api_roundtrip_and_real_lifecycle(tmp_path, custom_service):
    service = LocalModelService(tmp_path)
    app = FastAPI()
    register_local_model_routes(app, service)
    with TestClient(app, client=("127.0.0.1", 1234)) as client:
        payload = custom_service.model_dump(exclude={"kind"})
        created = client.post("/api/local-model", json=payload)
        assert created.status_code == 200
        item = created.json()
        assert item["kind"] is None
        key = item["id"]
        path = "/api/local-model/" + key
        assert Catalog(tmp_path).get(key)["executable"] == sys.executable
        status = client.get(path + "/status").json()
        assert status["actions"] == ["start", "stop"] and status["launchable"]
        assert status["online"] is False
        for action in ("load", "unload", "import"):
            assert client.post(path + "/operations", json={"action": action}).status_code == 400
        try:
            started = wait_job(client, client.post(path + "/operations", json={"action": "start"}).json())
            assert started["state"] == "succeeded", started
            status = client.get(path + "/status").json()
            assert status["online"] is True and status["managed"]
            assert status["models"] == [] and status["loaded"] is None
            received = json.loads((Path(custom_service.install_path) / "received.json").read_text(encoding="utf-8"))
            assert received == ["argument with spaces", "中文路径"]
            assert client.put(path, json=payload).status_code == 409
            assert client.delete(path).status_code == 409
            duplicate = wait_job(client, client.post(path + "/operations", json={"action": "start"}).json())
            assert duplicate["state"] == "failed"
            stopped = wait_job(client, client.post(path + "/operations", json={"action": "stop"}).json())
            assert stopped["state"] == "succeeded", stopped
            status = client.get(path + "/status").json()
            assert not status["online"] and not status["managed"]
            assert status["exit_code"] is not None
            assert client.delete(path).status_code == 200
            assert Path(custom_service.install_path).is_dir()
        finally:
            if service.managed(key):
                service.stop(service.adapter(key))


def test_unchecked_service_has_unknown_readiness(tmp_path):
    service = LocalModelService(tmp_path)
    config = ServiceConfig(name="worker", install_path=str(tmp_path), executable=sys.executable,
                           extra_args=["-c", "import time; time.sleep(60)"])
    item = service.save(config)
    # Multiple services without URLs are valid.
    service.save(config.model_copy(update={"name": "another worker"}))
    adapter = service.adapter(item["id"])
    try:
        result = service.start(adapter, "")
        assert "未配置就绪检测" in result["message"]
        status = service.inspect(item["id"])
        assert status["online"] is None and status["managed"]
    finally:
        if service.managed(item["id"]):
            service.stop(adapter)


def test_readiness_failure_preserves_process_for_explicit_stop(tmp_path, custom_service):
    config = custom_service.model_copy(update={"health_path": "/busy", "startup_timeout": 1})
    service = LocalModelService(tmp_path)
    item = service.save(config)
    adapter = service.adapter(item["id"])
    try:
        with pytest.raises(RuntimeError, match="HTTP 503"):
            service.start(adapter, "")
        assert service.managed(item["id"])
        assert not service.inspect(item["id"])["online"]
    finally:
        if service.managed(item["id"]):
            service.stop(adapter)


def test_exited_process_reports_failure_and_log(tmp_path, custom_service):
    config = custom_service.model_copy(update={"extra_args": ["-c", "raise SystemExit(7)"]})
    service = LocalModelService(tmp_path)
    item = service.save(config)
    with pytest.raises(RuntimeError, match="退出码 7.*日志"):
        service.start(service.adapter(item["id"]), "")
    assert service.inspect(item["id"])["exit_code"] == 7


def test_external_service_cannot_be_stopped_or_duplicated(tmp_path, custom_service):
    owner = LocalModelService(tmp_path / "owner")
    item = owner.save(custom_service)
    adapter = owner.adapter(item["id"])
    try:
        owner.start(adapter, "")
        observer = LocalModelService(tmp_path / "observer")
        registration = observer.save(ServiceConfig(name="Existing", endpoint=custom_service.endpoint, health_path="/ready"))
        remote = observer.adapter(registration["id"])
        status = observer.inspect(registration["id"])
        assert status["online"] and not status["managed"] and not status["launchable"]
        with pytest.raises(RuntimeError, match="只能停止"):
            observer.stop(remote)
        with pytest.raises(RuntimeError, match="在线"):
            observer.start(remote, "")
        assert owner.managed(item["id"])
    finally:
        if owner.managed(item["id"]):
            owner.stop(adapter)


def test_occupied_port_is_rejected_even_without_readiness(tmp_path, custom_service):
    from urllib.parse import urlsplit
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", urlsplit(custom_service.endpoint).port))
        sock.listen()
        service = LocalModelService(tmp_path)
        item = service.save(custom_service.model_copy(update={"health_path": ""}))
        with pytest.raises(RuntimeError, match="端口"):
            service.start(service.adapter(item["id"]), "")
        assert not service.managed(item["id"])


def test_script_launcher_stops_child_server(tmp_path, custom_service):
    launcher = Path(custom_service.install_path) / "launcher.py"
    launcher.write_text("import subprocess, sys\nsubprocess.Popen(sys.argv[1:]).wait()\n", encoding="utf-8")
    config = custom_service.model_copy(update={"extra_args": [str(launcher), sys.executable, *custom_service.extra_args]})
    service = LocalModelService(tmp_path)
    item = service.save(config)
    adapter = service.adapter(item["id"])
    try:
        service.start(adapter, "")
        assert LocalHttp(config.endpoint).probe_status("/ready")[0]
        service.stop(adapter)
        assert not LocalHttp(config.endpoint).probe_status("/ready")[0]
    finally:
        if service.managed(item["id"]):
            service.stop(adapter)


@pytest.mark.parametrize("patch", [
    {"kind": "unknown"}, {"executable": "relative.exe"}, {"health_path": "//example.com/health"},
    {"health_path": "/ok#fragment"}, {"health_path": "health"}, {"startup_timeout": 0},
    {"extra_args": ["first\nsecond"]}, {"endpoint": "http://127.0.0.1:0"},
    {"endpoint": "http://example.com:8080"}, {"python_path": sys.executable},
])
def test_custom_configuration_contract(custom_service, patch):
    with pytest.raises(ValidationError):
        ServiceConfig(**{**custom_service.model_dump(), **patch})


def test_custom_arguments_allow_flags_reserved_by_presets(tmp_path):
    config = ServiceConfig(name="custom", executable=sys.executable, install_path=str(tmp_path),
                           extra_args=["--port", "9000", "--config", "custom.json"])
    assert config.kind is None
    with pytest.raises(ValidationError, match="附加参数"):
        ServiceConfig(name="preset", kind="comfyui", install_path=str(tmp_path),
                      endpoint="http://127.0.0.1:8188", extra_args=config.extra_args)
