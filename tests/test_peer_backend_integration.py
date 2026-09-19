import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.peer_network.contracts import PeerCall, PeerGrant
from src.peer_network.delivery import DeliveryJournal
from src.providers.agent_runtime_context import AgentRuntimeContext
from src.web_backend.peer_operations import PeerOperations


def test_peer_operations_reach_real_backend_queue_with_remote_identity(monkeypatch, tmp_path):
    import src.web_backend as backend
    from src.web_backend import mobile_api, node_runtime, runtime_paths
    from src.web_backend.shared import envelope_text

    resource_root = backend._get_runtime_root()
    runtime_root = str(tmp_path / "AgentPark")
    for module in (backend, node_runtime, runtime_paths, mobile_api):
        monkeypatch.setattr(module, "_get_runtime_root", lambda: runtime_root)
    for module in (backend, node_runtime, runtime_paths):
        monkeypatch.setattr(module, "_get_resource_root", lambda: resource_root)
    facade = backend.WebBackendFacade()
    client = TestClient(facade.build(), base_url="http://127.0.0.1", client=("127.0.0.1", 1234))
    core = facade.core
    monkeypatch.setattr(core.graph_runtime, "_ensure_graph_runner", lambda graph_id: None)
    monkeypatch.setattr(core.graph_runtime, "_wake_graph_runner", lambda graph_id: None)
    assert client.post("/api/graphs/default", json={"graph": {"id": "default", "name": "Default", "output_routes": {}}}).status_code == 200
    assert client.post("/api/nodes/instances", json={"node_id": "target", "type_id": "agent_node", "name": "Target", "graph_id": "default"}).status_code == 200
    peer = PeerGrant(peer_id="b" * 64, name="Other backend", view=True, control=True, collaborate=True, graph_ids=["default"])
    operations = PeerOperations(core, DeliveryJournal(tmp_path / "deliveries.db"))
    assert operations.execute(peer, PeerCall(operation="nodes", graph_id="default"))["nodes"][0]["id"] == "target"
    call = PeerCall(operation="agent_message", graph_id="default", node_id="target", text="Review this task",
                    source_graph_id="work", source_node_id="sender", message_id="job-001")
    receipt = operations.execute(peer, call)
    assert receipt["queued"] and not receipt["completed"]
    assert operations.execute(peer, call)["duplicate"]
    item = core.node_ops.pop_node_instance_pending("target", {}, graph_id="default")["item"]
    assert item["_access_client_id"] == "peer:" + peer.peer_id
    assert item["_access_role"] == "nondeveloper"
    assert "work/sender" in envelope_text(item["payload"])
    assert "Review this task" in envelope_text(item["payload"])
    assert operations.execute(peer, PeerCall(operation="conversation", graph_id="default", node_id="target"))["state"] == "idle"
    assert client.get("/api/peers").status_code == 200
    saved = client.put("/api/peers/settings", json={"enabled": False, "server_ip": "203.0.113.10", "display_name": "工作电脑"})
    assert saved.status_code == 200
    assert saved.json()["settings"] == {"enabled": False, "server_ip": "203.0.113.10", "display_name": "工作电脑"}
    assert client.put("/api/peers/settings", json={"enabled": True, "access_token": "old-key"}).status_code == 400
    assert client.put("/api/peers/settings", json={"enabled": True, "server_ip": "https://example.com"}).status_code == 400
    assert client.put("/api/peers/grants", json=peer.model_dump()).status_code == 200
    assert client.delete("/api/peers/" + peer.peer_id).status_code == 200


def test_agent_tool_uses_runtime_source_and_keeps_delivery_semantics(monkeypatch):
    from functions import peer_network_tools
    from src.tool.base_tool import BaseTool
    agent = SimpleNamespace(_agentpark_runtime_context=AgentRuntimeContext(graph_id="local-graph", node_id="local-node"))
    tool = BaseTool(agent)
    tool.addTool("peer_network_tools")
    assert set(tool.function_map) == {"list_peer_devices", "peer_request"}
    requests = []
    def request(path, body=None):
        requests.append((path, body))
        return {"queued": True, "completed": False}
    monkeypatch.setattr(peer_network_tools, "_request", request)
    result = json.loads(peer_network_tools.peer_request("b" * 64, "agent_message", "target-g", "target-n",
                                                       "hello", "unique-request", agent=agent))
    assert result["result"]["completed"] is False
    assert requests[0][1]["source_graph_id"] == "local-graph"
    assert requests[0][1]["source_node_id"] == "local-node"
