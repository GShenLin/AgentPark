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
