import pytest
from fastapi.testclient import TestClient

from src.peer_network.portal_auth import PortalAuth
from src.peer_network.signaling import create_signaling_app


def test_eight_character_password_logs_in_and_wrong_password_is_rejected():
    with TestClient(create_signaling_app(portal_password="test1234"), base_url="http://127.0.0.1") as client:
        headers = {"origin": "http://127.0.0.1"}
        assert client.post("/portal/api/login", headers=headers, json={"password": "test1235"}).status_code == 401
        assert client.post("/portal/api/login", headers=headers, json={"password": "test1234"}).status_code == 204
        assert client.get("/portal/api/devices").status_code == 200


def test_password_length_validation_and_login_rate_limit_remain_active():
    with pytest.raises(ValueError, match="at least 8"):
        PortalAuth("short12")
    with TestClient(create_signaling_app(portal_password="test1234"), base_url="http://127.0.0.1") as client:
        headers = {"origin": "http://127.0.0.1"}
        for _ in range(5):
            assert client.post("/portal/api/login", headers=headers, json={"password": "wrong"}).status_code == 401
        assert client.post("/portal/api/login", headers=headers, json={"password": "test1234"}).status_code == 429
