import time


def test_basic_trigger_preserves_image_resource_for_downstream_node(tmp_path):
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
            "nodes": [
                {"id": "trigger", "typeId": "basic_trigger_node", "name": "trigger", "ui": {"x": 0, "y": 0}},
                {
                    "id": "receiver",
                    "typeId": "channel_receiver_node",
                    "name": "receiver",
                    "ui": {"x": 120, "y": 0},
                },
            ],
            "output_routes": {
                "trigger": [
                    {"output_index": 0, "targets": [{"node_id": "receiver", "input_index": 0}]},
                ],
            },
        }
        assert client.post("/api/graphs/default", json={"graph": graph}).status_code == 200
        for node_id, type_id in (
            ("trigger", "basic_trigger_node"),
            ("receiver", "channel_receiver_node"),
        ):
            response = client.post(
                "/api/nodes/instances",
                json={"node_id": node_id, "type_id": type_id, "graph_id": "default"},
            )
            assert response.status_code == 200

        response = client.post(
            "/api/nodes/instances/trigger/config?graph_id=default",
            json={"fields": {"OutputText": "configured-fallback"}},
        )
        assert response.status_code == 200

        image_path = str(tmp_path / "input.png")
        payload = {
            "role": "user",
            "parts": [
                {"type": "text", "text": "inspect this image"},
                {
                    "type": "resource",
                    "resource": {
                        "uri": image_path,
                        "name": "input.png",
                        "kind": "image",
                        "source": "test",
                    },
                },
            ],
        }

        assert client.post("/api/graphs/default/runner/start").status_code == 200
        response = client.post(
            "/api/graphs/default/emit",
            json={"from_id": "trigger", "payload": payload},
        )
        assert response.status_code == 200

        received_resource = None
        for _ in range(50):
            memory = client.get(
                "/api/nodes/instances/receiver/memory?graph_id=default&max_chars=20000",
            )
            if memory.status_code == 200:
                for message in memory.json().get("messages") or []:
                    for part in message.get("parts") or []:
                        if part.get("type") != "resource":
                            continue
                        resource = part.get("resource") or {}
                        if resource.get("uri") == image_path:
                            received_resource = resource
                            break
                    if received_resource:
                        break
            if received_resource:
                break
            time.sleep(0.1)

        assert received_resource is not None
        assert received_resource.get("kind") == "image"
        assert received_resource.get("name") == "input.png"
    finally:
        backend._get_runtime_root = original_get_runtime_root
        backend._get_resource_root = original_get_resource_root
