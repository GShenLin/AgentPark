from __future__ import annotations

from src.user_interaction_store import (
    create_interaction_request,
    list_interaction_requests,
    normalize_interaction_schema,
    submit_interaction_response,
    wait_for_interaction_response,
)


def test_interaction_store_submits_response(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_workspace_root", lambda: str(tmp_path))

    schema = normalize_interaction_schema(
        title="需要确认",
        fields=[
            {"id": "note", "type": "textarea", "label": "说明", "required": True},
            {
                "id": "choices",
                "type": "multiselect",
                "label": "选项",
                "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
            },
        ],
    )
    request = create_interaction_request(schema=schema, timeout_sec=30)

    pending = list_interaction_requests()
    assert [item["id"] for item in pending] == [request["id"]]

    submit_interaction_response(request["id"], {"values": {"note": "hello", "choices": ["a"]}})
    completed = wait_for_interaction_response(request["id"], timeout_sec=1)

    assert completed["status"] == "submitted"
    assert completed["response"]["values"]["note"] == "hello"
    assert list_interaction_requests() == []


def test_interaction_schema_rejects_invalid_select_options(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_workspace_root", lambda: str(tmp_path))

    try:
        normalize_interaction_schema(
            title="bad",
            fields=[{"id": "choice", "type": "select", "label": "Choice"}],
        )
    except ValueError as exc:
        assert "options is required" in str(exc)
    else:
        raise AssertionError("expected invalid schema to raise")


def test_interaction_schema_accepts_custom_html(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_workspace_root", lambda: str(tmp_path))

    schema = normalize_interaction_schema(
        title="custom",
        fields=[
            {
                "id": "designer",
                "type": "custom_html",
                "label": "设计器",
                "html": "<button>提交</button>",
                "css": "button { color: red; }",
                "js": "window.AITOOLS_INTERACTION.submit({ ok: true })",
                "height": 500,
                "initial_data": {"mode": "demo"},
            }
        ],
    )

    field = schema["fields"][0]
    assert field["type"] == "custom_html"
    assert field["height"] == 500
    assert field["initial_data"]["mode"] == "demo"


def test_interaction_schema_rejects_custom_html_without_html(tmp_path, monkeypatch):
    monkeypatch.setattr("src.user_interaction_store.get_workspace_root", lambda: str(tmp_path))

    try:
        normalize_interaction_schema(
            title="bad custom",
            fields=[{"id": "designer", "type": "custom_html", "label": "设计器"}],
        )
    except ValueError as exc:
        assert "html is required" in str(exc)
    else:
        raise AssertionError("expected invalid custom_html schema to raise")
