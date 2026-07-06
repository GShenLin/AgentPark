def test_private_network_preflight_header_present():
    import src.web_backend as backend
    from fastapi.testclient import TestClient

    client = TestClient(backend.create_app())

    response = client.options(
        "/api/nodes/instances/configs?graph_id=default",
        headers={
            "Origin": "http://example.test",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Private-Network": "true",
        },
    )

    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "*"
    assert response.headers["access-control-allow-private-network"] == "true"
