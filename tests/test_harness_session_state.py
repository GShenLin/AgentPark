from __future__ import annotations

import hashlib
import json

import pytest

from src.harness.session_state import resolve_state_directory


def legacy_directory(root, binding):
    directory = root / hashlib.sha256(json.dumps(binding, ensure_ascii=False).encode()).hexdigest()[:24]
    directory.mkdir(parents=True)
    return directory


def test_existing_native_history_is_adopted_in_place_and_survives_switches(tmp_path):
    binding = ["provider-a", "model-a", str(tmp_path), "instruction"]
    original = legacy_directory(tmp_path, binding)
    history = original / "history.txt"
    history.write_text("existing native conversation", encoding="utf-8")
    other_binding = ["provider-b", "model-b", str(tmp_path), "instruction"]
    other = legacy_directory(tmp_path, other_binding)
    assert resolve_state_directory(tmp_path, previous_binding=binding) == original
    assert resolve_state_directory(tmp_path, previous_binding=other_binding) == original
    assert history.read_text(encoding="utf-8") == "existing native conversation"
    assert other.is_dir()


def test_new_node_keeps_persisted_identity_and_other_nodes_are_separate(tmp_path):
    binding = ["p", "first", str(tmp_path), ""]
    first = resolve_state_directory(tmp_path / "node-a", previous_binding=binding)
    assert resolve_state_directory(tmp_path / "node-a", previous_binding=["q", "second", str(tmp_path), ""]) == first
    assert resolve_state_directory(tmp_path / "node-b", previous_binding=binding) != first


def test_unmatched_existing_history_does_not_silently_start_an_empty_session(tmp_path):
    legacy_directory(tmp_path, ["old", "model", str(tmp_path), ""])
    with pytest.raises(ValueError, match="Existing Harness conversations"):
        resolve_state_directory(tmp_path, previous_binding=["new", "model", str(tmp_path), ""])
    assert not (tmp_path / "current-session.json").exists()


def test_missing_pointer_does_not_abandon_existing_conversation(tmp_path):
    binding = ["p", "model", str(tmp_path), ""]
    original = resolve_state_directory(tmp_path, previous_binding=binding)
    (tmp_path / "current-session.json").unlink()
    with pytest.raises(ValueError, match="pointer is missing"):
        resolve_state_directory(tmp_path, previous_binding=binding)
    assert original.is_dir()


@pytest.mark.parametrize("state", [{}, {"schema": 1, "directory": "../outside"},
                                  {"schema": 1, "directory": "a" * 32}])
def test_invalid_or_missing_selected_state_is_not_replaced(tmp_path, state):
    pointer = tmp_path / "current-session.json"
    original = json.dumps(state)
    pointer.write_text(original, encoding="utf-8")
    with pytest.raises(ValueError):
        resolve_state_directory(tmp_path, previous_binding=["p", "m", str(tmp_path), ""])
    assert pointer.read_text(encoding="utf-8") == original
