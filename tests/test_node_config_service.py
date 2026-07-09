import json

import pytest

from src.web_backend.node_config_errors import NodeConfigFormatError, NodeConfigWriteError
from src.web_backend.node_config_service import NODE_CONFIG_SCHEMA_VERSION, node_config_service
from src.web_backend.state_store import _read_json_dict


def test_read_strict_rejects_corrupt_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(NodeConfigFormatError, match="invalid JSON"):
        node_config_service.read_strict(str(config_path))


def test_read_strict_rejects_non_object_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("[]", encoding="utf-8")

    with pytest.raises(NodeConfigFormatError, match="JSON object"):
        node_config_service.read_strict(str(config_path))


def test_read_optional_only_tolerates_missing_file(tmp_path):
    missing_path = tmp_path / "missing" / "config.json"

    assert node_config_service.read_optional_object(str(missing_path)) == {}


def test_read_optional_does_not_hide_corrupt_json(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text("{bad", encoding="utf-8")

    with pytest.raises(NodeConfigFormatError, match="invalid JSON"):
        node_config_service.read_optional_object(str(config_path))


def test_read_strict_migrates_missing_schema_version_in_memory(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"node_id":"n1"}', encoding="utf-8")

    payload = node_config_service.read_strict(str(config_path))

    assert payload["node_id"] == "n1"
    assert payload["schemaVersion"] == NODE_CONFIG_SCHEMA_VERSION


def test_read_strict_rejects_unsupported_schema_version(tmp_path):
    config_path = tmp_path / "config.json"
    config_path.write_text('{"schemaVersion":999,"node_id":"n1"}', encoding="utf-8")

    with pytest.raises(NodeConfigFormatError, match="unsupported node config schemaVersion"):
        node_config_service.read_strict(str(config_path))


def test_write_retries_transient_replace_failure(monkeypatch, tmp_path):
    import src.file_transaction as file_transaction

    config_path = tmp_path / "node" / "config.json"
    attempts = {"count": 0}
    original_replace = file_transaction.os.replace

    def flaky_replace(source, target):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise PermissionError("temporarily locked")
        return original_replace(source, target)

    monkeypatch.setattr(file_transaction.os, "replace", flaky_replace)

    node_config_service.write(str(config_path), {"node_id": "n1"})

    assert attempts["count"] == 3
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "node_id": "n1",
        "schemaVersion": NODE_CONFIG_SCHEMA_VERSION,
    }
    assert not config_path.with_name("runtime_state.json").exists()


def test_write_preserves_replace_error_after_retries(monkeypatch, tmp_path):
    import src.file_transaction as file_transaction

    config_path = tmp_path / "node" / "config.json"

    def locked_replace(_source, _target):
        raise PermissionError("still locked")

    monkeypatch.setattr(file_transaction.os, "replace", locked_replace)

    with pytest.raises(NodeConfigWriteError, match="still locked"):
        node_config_service.write(str(config_path), {"node_id": "n1"})


def test_apply_webui_payload_clears_named_fields(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    node_config_service.write(
        str(config_path),
        {
            "node_id": "n1",
            "type_id": "agent_node",
            "goal": "finish the task",
            "goal_state": {"status": "active"},
        },
    )

    result = node_config_service.apply_webui_payload(
        str(config_path),
        {"clear_fields": ["goal", "goal_state"]},
    )

    assert set(result.changed_fields) == {"goal", "goal_state"}
    assert "goal" not in result.after
    assert "goal_state" not in result.after
    assert json.loads(config_path.read_text(encoding="utf-8")) == {
        "node_id": "n1",
        "type_id": "agent_node",
        "schemaVersion": NODE_CONFIG_SCHEMA_VERSION,
    }
    assert not config_path.with_name("runtime_state.json").exists()


def test_apply_webui_payload_preserves_node_ui_size(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    node_config_service.write(
        str(config_path),
        {
            "node_id": "n1",
            "type_id": "agent_node",
            "ui": {"x": 10, "y": 20},
        },
    )

    result = node_config_service.apply_webui_payload(
        str(config_path),
        {"ui": {"x": 30, "y": 40, "width": 360, "height": 420}},
    )

    assert result.after["ui"] == {"x": 30, "y": 40, "width": 360, "height": 420}
    assert json.loads(config_path.read_text(encoding="utf-8"))["ui"] == {
        "x": 30,
        "y": 40,
        "width": 360,
        "height": 420,
    }


def test_write_splits_runtime_fields_from_config_json(tmp_path):
    config_path = tmp_path / "node" / "config.json"

    node_config_service.write(
        str(config_path),
        {
            "node_id": "n1",
            "type_id": "agent_node",
            "state": "working",
            "last_message": "large runtime output",
            "runtime_events": [{"type": "runtime_notice", "message": "running"}],
        },
    )

    saved_config = json.loads(config_path.read_text(encoding="utf-8"))

    assert "state" not in saved_config
    assert "last_message" not in saved_config
    assert "runtime_events" not in saved_config
    assert not config_path.with_name("runtime_state.json").exists()
    saved_runtime = _read_json_dict(str(config_path))
    assert saved_runtime["state"] == "working"
    assert saved_runtime["last_message"] == "large runtime output"
    assert saved_runtime["runtime_events"] == [{"type": "runtime_notice", "message": "running"}]
    assert node_config_service.read_strict(str(config_path))["last_message"] == "large runtime output"


def test_config_runtime_fields_are_split_on_write(tmp_path):
    config_path = tmp_path / "node" / "config.json"
    config_path.parent.mkdir()
    config_path.write_text(
        json.dumps(
            {
                "schemaVersion": 1,
                "node_id": "n1",
                "type_id": "agent_node",
                "state": "working",
                "pending": [{"id": "queued"}],
                "last_message": "runtime output",
                "goal_state": {"status": "active"},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    merged = node_config_service.read_strict(str(config_path))
    assert merged["state"] == "idle"
    assert "last_message" not in merged

    result = node_config_service.update(str(config_path), lambda cfg: cfg.update({"working_path": "C:/work"}))

    saved_config = json.loads(config_path.read_text(encoding="utf-8"))
    assert result.after["working_path"] == "C:/work"
    for key in ("state", "pending", "last_message", "goal_state"):
        assert key not in saved_config
    assert not config_path.with_name("runtime_state.json").exists()
