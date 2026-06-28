import json

import pytest

from src.node_config_overlay import load_node_config_file, merge_node_config_overlay


def test_load_node_config_file_returns_empty_when_missing(tmp_path):
    assert load_node_config_file(str(tmp_path)) == {}


def test_merge_node_config_overlay_applies_persisted_config(tmp_path):
    (tmp_path / "config.json").write_text(
        json.dumps({"provider_id": "persisted", "prompt": "from config"}),
        encoding="utf-8",
    )

    merged = merge_node_config_overlay({"provider_id": "runtime", "graph_id": "g1"}, str(tmp_path))

    assert merged == {"provider_id": "persisted", "graph_id": "g1", "prompt": "from config"}


def test_load_node_config_file_rejects_invalid_json(tmp_path):
    (tmp_path / "config.json").write_text("{bad", encoding="utf-8")

    with pytest.raises(ValueError, match="Failed to read node config"):
        load_node_config_file(str(tmp_path))


def test_load_node_config_file_requires_object(tmp_path):
    (tmp_path / "config.json").write_text("[1, 2, 3]", encoding="utf-8")

    with pytest.raises(ValueError, match="must contain a JSON object"):
        load_node_config_file(str(tmp_path))
