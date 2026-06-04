from pathlib import Path
import json


def test_node_capabilities_are_exposed_in_list_and_template(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root

    try:
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
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root


def test_node_instance_config_omits_schema_but_template_keeps_it(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root

    try:
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
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root


def test_raw_file_endpoint_serves_file_and_download_header(tmp_path):
    import src.web_backend as backend

    runtime_root = str(tmp_path)
    original_get_runtime_root = backend._get_runtime_root
    original_get_resource_root = backend._get_resource_root
    resource_root = original_get_runtime_root()

    backend._get_runtime_root = lambda: runtime_root
    backend._get_resource_root = lambda: resource_root

    try:
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
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
