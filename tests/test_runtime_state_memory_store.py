import pytest

from src.web_backend.runtime_state_memory_store import RuntimeStateContractError, RuntimeStateMemoryStore


def test_update_rejects_existing_invalid_runtime_projection(tmp_path):
    store = RuntimeStateMemoryStore()
    config_path = str(tmp_path / "node" / "config.json")
    key = store._key(config_path)
    store._items[key] = {"pending": "queued"}

    with pytest.raises(RuntimeStateContractError, match="pending must be a list"):
        store.update(config_path, lambda payload: payload.update({"state": "idle"}))


def test_snapshot_rejects_invalid_pending_count(tmp_path):
    store = RuntimeStateMemoryStore()
    config_path = str(tmp_path / "node" / "config.json")
    key = store._key(config_path)
    store._items[key] = {"pending_count": "1"}

    with pytest.raises(RuntimeStateContractError, match="pending_count must be a non-negative integer"):
        store.snapshot(config_path)


def test_field_projection_contains_explicit_defaults_and_tombstones(tmp_path):
    store = RuntimeStateMemoryStore()
    config_path = str(tmp_path / "node" / "config.json")

    projection = store.snapshot_fields(
        config_path,
        {"state", "pending_count", "inflight", "_stop_requested", "node_event_seq"},
    )

    assert projection == {
        "state": "idle",
        "pending_count": 0,
        "inflight": None,
        "_stop_requested": False,
        "node_event_seq": 0,
    }


def test_full_snapshot_has_sequence_but_does_not_materialize_optional_tombstones(tmp_path):
    store = RuntimeStateMemoryStore()
    config_path = str(tmp_path / "node" / "config.json")

    snapshot = store.snapshot(config_path)

    assert snapshot == {"state": "idle", "pending_count": 0, "node_event_seq": 0}
