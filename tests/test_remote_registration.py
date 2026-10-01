import json
import threading
from types import SimpleNamespace

import pytest

from src.providers.curl_types import CurlHttpError, CurlResponse, CurlTransportError
from src.remote_worker.endpoint import resolve_endpoint
from src.remote_workspace.broker import RemoteWorkspaceBroker
from src.web_backend.remote_workspace_api import RemoteWorkspaceApiDomain


class EndpointTransport:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.urls = []

    def request(self, **kwargs):
        self.urls.append(kwargs["url"])
        item = next(self.responses)
        if isinstance(item, Exception):
            raise item
        return item


def descriptor(service):
    return CurlResponse(json.dumps({"service": service, "remote_protocol": 2}), 200)


def test_target_ip_prefers_runtime_8788_and_falls_back_to_center_only_when_unavailable():
    transport = EndpointTransport([descriptor("agentpark-runtime")])
    endpoint = resolve_endpoint("10.2.3.4", transport)
    assert endpoint.kind == "runtime" and endpoint.origin == "http://10.2.3.4:8788"
    assert len(transport.urls) == 1
    for missing in [CurlResponse("not found", 404), CurlTransportError("connection refused")]:
        transport = EndpointTransport([missing, descriptor("agentpark-coordinator")])
        endpoint = resolve_endpoint("203.0.113.10", transport)
        assert endpoint.kind == "coordinator" and endpoint.origin == "https://203.0.113.10"
        assert transport.urls == ["http://203.0.113.10:8788/api/remote-workers/service",
                                  "https://203.0.113.10/api/remote-workers/service"]


@pytest.mark.parametrize("status", [401, 403, 500])
def test_target_does_not_switch_servers_after_rejected_registration_probe(status):
    transport = EndpointTransport([CurlResponse("rejected", status)])
    with pytest.raises(CurlHttpError):
        resolve_endpoint("10.2.3.4", transport)
    assert len(transport.urls) == 1


def test_invalid_endpoint_or_protocol_does_not_trigger_a_fallback():
    for address in ["host/path", "user:password@host", "host?query=1"]:
        with pytest.raises(ValueError):
            resolve_endpoint(address, EndpointTransport([]))
    transport = EndpointTransport([CurlResponse('{"service":"other"}', 200)])
    with pytest.raises(ValueError):
        resolve_endpoint("10.2.3.4", transport)
    assert len(transport.urls) == 1


def registration():
    return {"protocol_version": 2, "worker_id": "worker", "token": "secret", "display_name": "Workstation",
            "host_kind": "standalone", "workspace_path": "C:/Workspace", "capabilities": ["read_file"]}


def test_registered_worker_is_visible_from_a_different_browser_ip():
    api = RemoteWorkspaceApiDomain()
    api.broker.register(registration(), "10.0.0.8")
    workers = api.list_workers(SimpleNamespace(client=SimpleNamespace(host="192.168.1.5")))["workers"]
    assert workers[0]["worker_id"] == "worker"
    assert workers[0]["connection_kind"] == "direct"
    assert "token" not in workers[0]


def test_same_worker_reconnect_preserves_an_executing_task():
    broker = RemoteWorkspaceBroker()
    broker.register(registration(), "10.0.0.8")
    results = []
    errors = []

    def execute():
        try:
            results.append(broker.execute({"worker_id": "worker", "tool_name": "read_file",
                                           "working_path": "C:/Workspace", "timeout_seconds": 2}))
        except Exception as exc:
            errors.append(exc)
    thread = threading.Thread(target=execute)
    thread.start()
    task = broker.poll("worker", "secret", 1)
    assert task is not None
    broker.register(registration(), "192.168.1.8")
    broker.submit_result("worker", "secret", task["task_id"], {"ok": True, "result": "completed"})
    thread.join(3)
    assert not errors and results == ["completed"]


def test_expired_queued_task_is_not_executed_after_worker_returns():
    broker = RemoteWorkspaceBroker()
    broker.register(registration(), "10.0.0.8")
    with pytest.raises(TimeoutError):
        broker.execute({"worker_id": "worker", "tool_name": "read_file", "working_path": "C:/Workspace",
                        "timeout_seconds": 1})
    assert broker.poll("worker", "secret", 0) is None
