from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.access_policy import load_access_policy
from src.access_policy import nondeveloper_filtered_tools
from src.access_policy import save_access_policy
from src.tool.access_filter import filter_configured_tool_modules
from src.tool.access_filter import filter_registered_agent_tools
from src.web_backend.access_api import AccessApiDomain


def _request(host: str, *, client_id: str = "", username: str = ""):
    headers = {}
    if client_id:
        headers["x-agentpark-client-id"] = client_id
    if username:
        headers["x-agentpark-username"] = username
    return SimpleNamespace(client=SimpleNamespace(host=host), headers=headers)


def test_remote_user_registration_records_username_ip_and_defaults_to_nondeveloper(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))
    api = AccessApiDomain()

    missing = api.get_status(_request("10.0.0.8", client_id="browser-1"))
    assert missing["username_required"] is True

    status = api.get_status(_request("10.0.0.8", client_id="browser-1", username="Alice"))
    assert status["username"] == "Alice"
    assert status["role"] == "nondeveloper"
    assert status["is_developer"] is False
    assert api.message_access_metadata(
        _request("10.0.0.8", client_id="browser-1", username="Alice")
    ) == {
        "_access_client_id": "browser-1",
        "_access_username": "Alice",
        "_access_role": "nondeveloper",
    }

    policy = load_access_policy()
    assert policy["users"] == [
        {
            "clientIds": ["browser-1"],
            "username": "Alice",
            "developer": False,
            "ips": ["10.0.0.8"],
            "firstSeenAt": policy["users"][0]["firstSeenAt"],
            "lastSeenAt": policy["users"][0]["lastSeenAt"],
        }
    ]


def test_backend_username_edit_and_developer_permission_are_authoritative(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))
    api = AccessApiDomain()
    request = _request("10.0.0.8", client_id="browser-1", username="Typo")
    api.get_status(request)
    policy = load_access_policy()
    policy["users"][0]["username"] = "Alice"
    policy["users"][0]["developer"] = True
    save_access_policy(policy)

    status = api.get_status(request)
    assert status["username"] == "Alice"
    assert status["role"] == "developer"
    assert api.get_settings(request)["data"]["users"][0]["developer"] is True


def test_same_username_across_devices_is_one_user(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))
    api = AccessApiDomain()

    first = api.get_status(
        _request("10.0.0.8", client_id="browser-1", username="Alice")
    )
    policy = load_access_policy()
    policy["users"][0]["developer"] = True
    save_access_policy(policy)

    second = api.get_status(
        _request("10.0.0.9", client_id="browser-2", username="alice")
    )

    assert first["username"] == "Alice"
    assert second["client_id"] == "browser-2"
    assert second["username"] == "Alice"
    assert second["is_developer"] is True
    policy = load_access_policy()
    assert len(policy["users"]) == 1
    assert policy["users"][0]["clientIds"] == ["browser-1", "browser-2"]
    assert policy["users"][0]["ips"] == ["10.0.0.8", "10.0.0.9"]


def test_legacy_same_username_records_are_merged(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))

    policy = save_access_policy(
        {
            "users": [
                {
                    "clientId": "browser-1",
                    "username": "Alice",
                    "developer": False,
                    "ips": ["10.0.0.8"],
                    "firstSeenAt": "2026-01-02T00:00:00+00:00",
                    "lastSeenAt": "2026-01-02T00:00:00+00:00",
                },
                {
                    "clientId": "browser-2",
                    "username": "alice",
                    "developer": True,
                    "ips": ["10.0.0.9"],
                    "firstSeenAt": "2026-01-01T00:00:00+00:00",
                    "lastSeenAt": "2026-01-03T00:00:00+00:00",
                },
            ],
            "nonDeveloperFilteredTools": [],
        }
    )

    assert policy["users"] == [
        {
            "clientIds": ["browser-1", "browser-2"],
            "username": "Alice",
            "developer": True,
            "ips": ["10.0.0.8", "10.0.0.9"],
            "firstSeenAt": "2026-01-01T00:00:00+00:00",
            "lastSeenAt": "2026-01-03T00:00:00+00:00",
        }
    ]


def test_nondeveloper_cannot_update_access_settings(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))
    api = AccessApiDomain()
    request = _request("10.0.0.8", client_id="browser-1", username="Alice")
    api.get_status(request)

    with pytest.raises(HTTPException) as error:
        api.update_settings(load_access_policy(), request)
    assert error.value.status_code == 403


def test_local_request_is_developer_without_registration(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))
    status = AccessApiDomain().get_status(_request("127.0.0.1"))
    assert status["is_developer"] is True
    assert status["username_required"] is False
    assert load_access_policy()["users"] == []


def test_nondeveloper_tool_filter_handles_modules_and_registered_functions(monkeypatch, tmp_path):
    monkeypatch.setattr("src.access_policy.get_workspace_root", lambda: str(tmp_path))
    blocked = nondeveloper_filtered_tools()
    assert filter_configured_tool_modules(
        ["file_read_tools", "system_tools", "code_edit_tools"],
        blocked,
    ) == ("file_read_tools",)

    tools = SimpleNamespace(
        tool_declarations=[
            {"type": "function", "function": {"name": "read_file"}},
            {"type": "function", "function": {"name": "execute_console_command"}},
        ],
        function_map={
            "read_file": object(),
            "execute_console_command": object(),
            "apply_patch": object(),
        },
    )
    agent = SimpleNamespace(tools=tools)
    removed = filter_registered_agent_tools(agent, ["execute_console_command", "apply_patch"])
    assert removed == ("execute_console_command", "apply_patch")
    assert [item["function"]["name"] for item in tools.tool_declarations] == ["read_file"]
    assert set(tools.function_map) == {"read_file"}
