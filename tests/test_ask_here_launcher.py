from __future__ import annotations

import pytest

from src import ask_here_launcher


def test_dispatch_folder_launches_single_running_pet(monkeypatch, tmp_path):
    calls = []

    def fake_request_json(method, url, payload=None, *, timeout=ask_here_launcher.DEFAULT_TIMEOUT_SECONDS):
        calls.append((method, url, payload))
        if method == "GET":
            return {
                "views": [
                    {
                        "view_id": "view-1",
                        "graph_id": "default",
                        "node_id": "Agent",
                        "visible": True,
                        "pinned": True,
                    }
                ]
            }
        return {"ok": True, "pid": 123}

    monkeypatch.setattr(ask_here_launcher, "resolve_server_base_url", lambda: "http://127.0.0.1:8788")
    monkeypatch.setattr(ask_here_launcher, "_request_json", fake_request_json)

    result = ask_here_launcher.dispatch_folder(str(tmp_path))

    assert result["mode"] == "single_pet"
    assert calls[1][0] == "POST"
    assert calls[1][1] == "http://127.0.0.1:8788/api/node-desktop-views/launch"
    assert calls[1][2]["working_path"] == str(tmp_path)
    assert calls[1][2]["open_chat"] is True
    assert calls[1][2]["draft_prefix"] == f"{tmp_path}\n"


def test_dispatch_file_launches_single_pet_without_changing_working_path(monkeypatch, tmp_path):
    target_file = tmp_path / "sample.txt"
    target_file.write_text("hello", encoding="utf-8")
    calls = []

    def fake_request_json(method, url, payload=None, *, timeout=ask_here_launcher.DEFAULT_TIMEOUT_SECONDS):
        calls.append((method, url, payload))
        if method == "GET":
            return {
                "views": [
                    {
                        "view_id": "view-1",
                        "graph_id": "default",
                        "node_id": "Agent",
                        "visible": True,
                        "pinned": True,
                    }
                ]
            }
        return {"ok": True, "pid": 123}

    monkeypatch.setattr(ask_here_launcher, "resolve_server_base_url", lambda: "http://127.0.0.1:8788")
    monkeypatch.setattr(ask_here_launcher, "_request_json", fake_request_json)

    result = ask_here_launcher.dispatch_folder(str(target_file))

    assert result["mode"] == "single_pet"
    assert calls[1][0] == "POST"
    assert "working_path" not in calls[1][2]
    assert calls[1][2]["draft_prefix"] == f"{target_file}\n"


def test_dispatch_folder_opens_picker_for_multiple_running_pets(monkeypatch, tmp_path):
    opened = []

    def fake_request_json(method, url, payload=None, *, timeout=ask_here_launcher.DEFAULT_TIMEOUT_SECONDS):
        assert method == "GET"
        return {
            "views": [
                {"view_id": "view-1", "graph_id": "default", "node_id": "A", "visible": True},
                {"view_id": "view-2", "graph_id": "default", "node_id": "B", "visible": True},
            ]
        }

    monkeypatch.setattr(ask_here_launcher, "resolve_server_base_url", lambda: "http://127.0.0.1:8788")
    monkeypatch.setattr(ask_here_launcher, "_request_json", fake_request_json)
    monkeypatch.setattr(ask_here_launcher.webbrowser, "open_new_tab", lambda url: opened.append(url) or True)

    result = ask_here_launcher.dispatch_folder(str(tmp_path))

    assert result["mode"] == "picker"
    assert result["pet_count"] == 2
    assert opened == [result["url"]]
    assert "ask_here=1" in result["url"]


def test_dispatch_folder_prefers_matching_pet_over_count(monkeypatch, tmp_path):
    calls = []
    other_path = tmp_path / "other"
    other_path.mkdir()

    def fake_request_json(method, url, payload=None, *, timeout=ask_here_launcher.DEFAULT_TIMEOUT_SECONDS):
        calls.append((method, url, payload))
        if method == "GET":
            return {
                "views": [
                    {
                        "view_id": "view-1",
                        "graph_id": "default",
                        "node_id": "A",
                        "visible": True,
                        "node": {"working_path": str(other_path)},
                    },
                    {
                        "view_id": "view-2",
                        "graph_id": "default",
                        "node_id": "B",
                        "visible": True,
                        "node": {"working_path": str(tmp_path)},
                    },
                ]
            }
        return {"ok": True, "pid": 456}

    monkeypatch.setattr(ask_here_launcher, "resolve_server_base_url", lambda: "http://127.0.0.1:8788")
    monkeypatch.setattr(ask_here_launcher, "_request_json", fake_request_json)

    result = ask_here_launcher.dispatch_folder(str(tmp_path))

    assert result["mode"] == "matching_pet"
    assert calls[1][0] == "POST"
    assert calls[1][2]["node_id"] == "B"
    assert calls[1][2]["working_path"] == str(tmp_path)
    assert calls[1][2]["open_chat"] is True


def test_dispatch_folder_rejects_missing_path(tmp_path):
    missing = tmp_path / "missing"

    with pytest.raises(ask_here_launcher.AskHereError):
        ask_here_launcher.dispatch_folder(str(missing))
