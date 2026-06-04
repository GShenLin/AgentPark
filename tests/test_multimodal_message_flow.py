import time


def test_emit_graph_accepts_message_envelope_and_persists_messages(tmp_path):
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

        graph = {
            "id": "default",
            "name": "default",
            "links": [],
        }
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        assert (
            client.post(
                "/api/nodes/instances",
                json={"node_id": "echo_mm", "type_id": "echo_node", "graph_id": "default"},
            ).status_code
            == 200
        )
        assert client.post("/api/graphs/default/runner/start").status_code == 200

        payload = {
            "role": "user",
            "parts": [
                {"type": "text", "text": "describe this resource"},
                {
                    "type": "resource",
                    "resource": {
                        "uri": "C:/tmp/example.png",
                        "kind": "image",
                        "name": "example.png",
                        "source": "upload",
                    },
                },
            ],
        }
        assert (
            client.post(
                "/api/graphs/default/emit",
                json={
                    "from_id": "echo_mm",
                    "payload": payload,
                },
            ).status_code
            == 200
        )

        ok = False
        for _ in range(40):
            cfgs = client.get("/api/nodes/instances/configs?graph_id=default")
            if cfgs.status_code == 200:
                nodes = cfgs.json().get("nodes") or []
                cfg = next((item for item in nodes if str(item.get("node_id") or "") == "echo_mm"), None)
                if isinstance(cfg, dict):
                    last = str(cfg.get("last_message") or "")
                    if "describe this resource" in last and "example.png" in last:
                        ok = True
                        break
            time.sleep(0.1)

        assert ok, "structured message envelope was not processed by graph runner"

        mem = client.get("/api/nodes/instances/echo_mm/memory?graph_id=default&max_chars=20000")
        assert mem.status_code == 200
        body = mem.json() or {}
        messages = body.get("messages")
        assert isinstance(messages, list)
        assert messages, "messages.jsonl should include structured message entries"
        has_resource = False
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            for part in msg.get("parts") or []:
                if not isinstance(part, dict):
                    continue
                if str(part.get("type") or "") == "resource":
                    res = part.get("resource") or {}
                    if isinstance(res, dict) and str(res.get("kind") or "") == "image":
                        has_resource = True
                        break
            if has_resource:
                break
        assert has_resource, "resource part was not persisted in node messages"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
