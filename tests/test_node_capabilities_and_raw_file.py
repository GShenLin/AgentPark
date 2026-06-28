from pathlib import Path
import json
from contextlib import contextmanager


@contextmanager
def _patched_backend_paths(backend, runtime_root: str):
    from src.web_backend import runtime_paths as runtime_paths_module

    original_backend_runtime_root = backend._get_runtime_root
    original_backend_resource_root = backend._get_resource_root
    original_runtime_paths_runtime_root = runtime_paths_module._get_runtime_root
    original_runtime_paths_resource_root = runtime_paths_module._get_resource_root
    resource_root = original_backend_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root
    runtime_paths_module._get_runtime_root = lambda: runtime_root
    runtime_paths_module._get_resource_root = lambda: resource_root
    try:
        yield
    finally:
        backend._get_runtime_root = original_backend_runtime_root
        backend._get_resource_root = original_backend_resource_root
        runtime_paths_module._get_runtime_root = original_runtime_paths_runtime_root
        runtime_paths_module._get_resource_root = original_runtime_paths_resource_root


def test_node_capabilities_are_exposed_in_list_and_template(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)

    with _patched_backend_paths(backend, runtime_root):
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        listed = client.get("/api/nodes")
        assert listed.status_code == 200
        nodes = listed.json().get("nodes") or []
        agent = next((item for item in nodes if str(item.get("id") or "") == "agent_node"), None)
        assert isinstance(agent, dict)
        assert "accepts" in agent
        assert "produces" in agent
        assert "resource:image" in (agent.get("accepts") or [])
        assert "resource:video" in (agent.get("produces") or [])

        template = client.get("/api/nodes/templates/agent_node")
        assert template.status_code == 200
        payload = template.json() or {}
        assert "accepts" in payload
        assert "produces" in payload
        assert "resource:image" in (payload.get("accepts") or [])
        assert "resource:video" in (payload.get("produces") or [])
        assert isinstance(payload.get("schema"), dict)
        assert "provider_id" in (payload.get("schema") or {})

        listed_ids = {str(item.get("id") or "") for item in nodes if isinstance(item, dict)}
        assert "agent_mcp_loader" not in listed_ids
        assert "agent_plugin_loader" not in listed_ids
        assert "agent_skill_dependencies" not in listed_ids
        assert "agent_node_settings" not in listed_ids


def test_node_instance_config_omits_schema_but_template_keeps_it(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)

    with _patched_backend_paths(backend, runtime_root):
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        created = client.post(
            "/api/nodes/instances",
            json={"node_id": "agent1", "type_id": "agent_node", "graph_id": "default"},
        )
        assert created.status_code == 200
        config_path = Path(created.json()["config_path"])
        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert "schema" not in config

        listed = client.get("/api/nodes/instances/configs", params={"graph_id": "default"})
        assert listed.status_code == 200
        nodes = listed.json().get("nodes") or []
        agent_cfg = next((item for item in nodes if str(item.get("node_id") or "") == "agent1"), None)
        assert isinstance(agent_cfg, dict)
        assert "schema" not in agent_cfg

        template = client.get("/api/nodes/templates/agent_node")
        assert template.status_code == 200
        assert "provider_id" in (template.json().get("schema") or {})


def test_agent_node_plugin_and_mcp_fields_persist_through_config_api(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)

    with _patched_backend_paths(backend, runtime_root):
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)

        created = client.post(
            "/api/nodes/instances",
            json={"node_id": "agent1", "type_id": "agent_node", "graph_id": "default"},
        )
        assert created.status_code == 200
        config_path = Path(created.json()["config_path"])

        updated = client.post(
            "/api/nodes/instances/agent1/config",
            params={"graph_id": "default"},
            json={
                "fields": {
                    "plugins": ["core-dev"],
                    "tools": ["rg_tools"],
                    "skills": ["ue5-cpp-gameplay"],
                    "mcp_servers": ["docs"],
                }
            },
        )
        assert updated.status_code == 200

        config = json.loads(config_path.read_text(encoding="utf-8"))
        assert config["plugins"] == ["core-dev"]
        assert config["tools"] == ["rg_tools"]
        assert config["skills"] == ["ue5-cpp-gameplay"]
        assert config["mcp_servers"] == ["docs"]

        listed = client.get("/api/nodes/instances/configs", params={"graph_id": "default"})
        assert listed.status_code == 200
        nodes = listed.json().get("nodes") or []
        agent_cfg = next((item for item in nodes if str(item.get("node_id") or "") == "agent1"), None)
        assert isinstance(agent_cfg, dict)
        assert agent_cfg["plugins"] == ["core-dev"]
        assert agent_cfg["mcp_servers"] == ["docs"]


def test_raw_file_endpoint_serves_file_and_download_header(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)

    with _patched_backend_paths(backend, runtime_root):
        app = backend.create_app()
        from fastapi.testclient import TestClient

        client = TestClient(app)
        payload_path = Path(runtime_root) / "assets" / "demo.txt"
        payload_path.parent.mkdir(parents=True, exist_ok=True)
        payload_path.write_text("raw-file-ok", encoding="utf-8")

        served = client.get("/api/files/raw", params={"path": str(payload_path)})
        assert served.status_code == 200
        assert served.text == "raw-file-ok"

        downloaded = client.get("/api/files/raw", params={"path": str(payload_path), "download": "1"})
        assert downloaded.status_code == 200
        disposition = str(downloaded.headers.get("content-disposition") or "")
        assert "attachment" in disposition.lower()
        assert "demo.txt" in disposition
