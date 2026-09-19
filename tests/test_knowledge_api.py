import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.knowledge.contracts import LibraryConfig
from src.knowledge.service import KnowledgeService
from src.knowledge.skill import execute
from src.provider_api_key_store import add_api_key_alias, api_key_store_path
from src.web_backend.knowledge_api import register_knowledge_routes


@pytest.fixture
def setup(tmp_path):
    service = KnowledgeService(tmp_path)
    app = FastAPI()
    register_knowledge_routes(app, service)
    folder = tmp_path / "notes"
    folder.mkdir()
    add_api_key_alias(api_key_store_path(str(tmp_path)), name="shared-key", api_key="example-secret")
    config = LibraryConfig(name="test", folder=str(folder), embedding_url="http://localhost:1234/v1",
                           embedding_model="local", dimensions=8, api_key_alias="shared-key", allow_agents=True)
    yield service, app, config
    service.close()


def test_api_owner_gate_secret_retention_and_validation(setup):
    service, app, config = setup
    remote = TestClient(app, client=("192.0.2.1", 5000))
    assert remote.get("/api/knowledge").status_code == 403
    local = TestClient(app, client=("127.0.0.1", 5000))
    created = local.post("/api/knowledge", json=config.model_dump())
    assert created.status_code == 200
    key = created.json()["id"]
    assert "example-secret" not in created.text
    assert "example-secret" not in local.get("/api/knowledge").text
    assert created.json()["api_key_alias"] == "shared-key"
    assert "example-secret" not in service.catalog.path.read_bytes().decode("utf-8", errors="ignore")
    payload = {**config.model_dump(), "name": "changed", "api_key_alias": None, "retry_interval_seconds": 12}
    assert local.put(f"/api/knowledge/{key}", json=payload).status_code == 200
    assert service.catalog.get(key).api_key_alias == "shared-key"
    assert service.catalog.get(key).retry_interval_seconds == 12
    assert local.get("/api/knowledge").json()["libraries"][0]["retry_interval_seconds"] == 12
    assert local.put(f"/api/knowledge/{key}", json={**payload, "dimensions": 16}).status_code == 400
    assert local.post(f"/api/knowledge/{key}/search", json={"query": "cats", "limit": 999}).status_code == 422
    assert local.get(f"/api/knowledge/{key}/documents?limit=100000").status_code == 422


def test_real_spawned_worker_and_restart_recovery(setup):
    service, app, config = setup
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            requests.append((self.path, self.headers.get("Authorization")))
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            result = {"data": [{"index": index, "embedding": [1.0, 0.2, 0.1, 0, 0, 0, 0, 0]}
                               for index, _ in enumerate(body["input"])]}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(result).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        config = config.model_copy(update={"embedding_url": f"http://127.0.0.1:{server.server_port}/v1/embeddings"})
        from pathlib import Path
        (Path(config.folder) / "a.md").write_text("cats and knowledge", encoding="utf-8")
        key = service.catalog.create(config)["id"]
        from src.knowledge.scanner import begin_scan
        store = service.store(key)
        begin_scan(store)
        # Simulate a previous process disappearing while its persisted task was running.
        with store.connect() as db:
            db.execute("UPDATE job SET status='running'")
        service.start()
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            status = store.status()
            if status["status"] in {"completed", "failed"}:
                break
            time.sleep(0.1)
        assert status["status"] == "completed", status
        client = TestClient(app, client=("127.0.0.1", 5000))
        result = client.post(f"/api/knowledge/{key}/search", json={"query": "feline"})
        assert result.status_code == 200, result.text
        assert result.json()["matches"][0]["path"] == "a.md"
        assert result.json()["partial"] is False
        assert client.post(f"/api/knowledge/{key}/test").json() == {"ok": True, "dimensions": 8}
        assert execute(service.catalog.workspace, {"action": "search", "library_id": key, "query": "feline"})["matches"]
        assert len(requests) == 5  # dimension detection, worker batch, API search, connection test, Skill search
        assert all(path == "/v1/embeddings" and auth == "Bearer example-secret" for path, auth in requests)
    finally:
        service.close()
        server.shutdown()
        server.server_close()


def test_single_workspace_writer_lease(setup):
    service, _, _ = setup
    service.start()
    other = KnowledgeService(service.catalog.workspace)
    with pytest.raises(RuntimeError, match="另一个"):
        other.start()
    service.close()
    other.start()
    other.close()
