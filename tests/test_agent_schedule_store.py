from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.agent_schedule_store import AgentScheduleStore


@pytest.fixture
def store(tmp_path):
    return AgentScheduleStore(tmp_path / "schedules.sqlite")


@pytest.fixture
def owner():
    return {"graph_id": "graph", "node_id": "node", "task_id": "task", "access_metadata": {"scope": ["read"]}}


def create(store, owner, **changes):
    params = {"prompt": "check progress", "delay_seconds": 10, "idempotency_key": "key"}
    params.update(changes)
    return store.manage(owner, "create", **params)


def stamp(schedule, seconds=0):
    return datetime.fromisoformat(schedule["run_at"].replace("Z", "+00:00")) + timedelta(seconds=seconds)


def test_create_persist_and_scope(store, owner):
    item = create(store, owner)
    reopened = AgentScheduleStore(store.path)
    assert reopened.manage(owner, "get", schedule_id=item["schedule_id"]) == item
    assert item["run_at"].endswith("Z")
    assert item["access_metadata"] == owner["access_metadata"]
    assert reopened.manage({**owner, "task_id": "other"}, "list")["schedules"] == [item]
    for change in ({"node_id": "other"}, {"graph_id": "other"}):
        stranger = {**owner, **change}
        assert store.manage(stranger, "list") == {"schedules": []}
        with pytest.raises(KeyError):
            store.manage(stranger, "cancel", schedule_id=item["schedule_id"], expected_revision=1)


def test_idempotency(store, owner):
    first = create(store, owner)
    assert create(store, owner) == first
    other = create(store, {**owner, "task_id": "another"})
    assert other["schedule_id"] != first["schedule_id"]
    assert other["task_id"] == "another"
    with pytest.raises(ValueError, match="different request"):
        create(store, owner, prompt="different")


@pytest.mark.parametrize("value", [True, False, 0, -1, float("nan"), float("inf"), "10", None, 10**1000])
def test_invalid_delays(store, owner, value):
    with pytest.raises(ValueError):
        create(store, owner, delay_seconds=value)


@pytest.mark.parametrize("value", [True, 0, 59.9, -1, float("inf"), "60"])
def test_invalid_intervals(store, owner, value):
    with pytest.raises(ValueError):
        create(store, owner, interval_seconds=value)


@pytest.mark.parametrize("value", ["2099-01-01T00:00:00", "nonsense", "2000-01-01T00:00:00Z", True])
def test_invalid_dates(store, owner, value):
    with pytest.raises(ValueError):
        store.manage(owner, "create", prompt="test", run_at=value, idempotency_key="key")


def test_conflicting_and_missing_timing(store, owner):
    with pytest.raises(ValueError):
        create(store, owner, run_at="2099-01-01T00:00:00Z")
    with pytest.raises(ValueError):
        store.manage(owner, "create", prompt="test", idempotency_key="key")
    with pytest.raises(ValueError):
        create(store, owner, unknown="bad")


def test_offset_normalization(store, owner):
    item = store.manage(owner, "create", prompt="test", run_at="2099-01-01T02:00:00+02:00", idempotency_key="key")
    assert item["run_at"] == "2099-01-01T00:00:00Z"


def test_occurrence_claim_finish(store, owner):
    item = create(store, owner)
    assert store.due(stamp(item, -1)) == []
    delivery, = store.due(stamp(item))
    assert delivery["task_id"] == "task"
    assert delivery["access_metadata"] == owner["access_metadata"]
    assert store.due(stamp(item, 100)) == [delivery]
    assert store.begin(delivery["occurrence_id"], "wrong", "node") is None
    claimed = store.begin(delivery["occurrence_id"], "graph", "node")
    assert claimed["status"] == "running"
    assert store.begin(delivery["occurrence_id"], "graph", "node") is None
    store.finish(delivery["occurrence_id"])
    assert store.due(stamp(item, 100)) == []
    assert store.manage(owner, "get", schedule_id=item["schedule_id"])["status"] == "completed"


def test_recurring_coalesces_and_preserves_anchor(store, owner):
    item = create(store, owner, interval_seconds=60)
    delivery, = store.due(stamp(item, 181))
    updated = store.manage(owner, "get", schedule_id=item["schedule_id"])
    assert stamp(updated) == stamp(item, 240)
    assert store.due(stamp(item, 1000)) == [delivery]
    store.begin(delivery["occurrence_id"], "graph", "node")
    store.finish(delivery["occurrence_id"])
    next_delivery, = store.due(stamp(item, 1000))
    assert next_delivery["occurrence_id"] != delivery["occurrence_id"]
    assert stamp(store.manage(owner, "get", schedule_id=item["schedule_id"])) == stamp(item, 1020)


def test_update_revision_and_pending_cancellation(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    with pytest.raises(ValueError):
        store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=0, prompt="new")
    revised = store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=1, prompt="new", delay_seconds=100, interval_seconds=60)
    assert revised["revision"] == 2
    assert revised["status"] == "active"
    assert store.begin(delivery["occurrence_id"], "graph", "node") is None
    revised = store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=2, interval_seconds=None)
    assert revised["interval_seconds"] is None
    later, = store.due(stamp(revised))
    assert later["prompt"] == "new"


def test_cancel_pending_and_leave_running(store, owner):
    item = create(store, owner, interval_seconds=60)
    delivery, = store.due(stamp(item))
    store.manage(owner, "cancel", schedule_id=item["schedule_id"], expected_revision=1)
    assert store.due(stamp(item, 1000)) == []
    assert store.begin(delivery["occurrence_id"], "graph", "node") is None
    second = create(store, owner, idempotency_key="second")
    running, = store.due(stamp(second))
    store.begin(running["occurrence_id"], "graph", "node")
    store.manage(owner, "cancel", schedule_id=second["schedule_id"], expected_revision=1)
    assert store.due(stamp(second))[0]["status"] == "running"
    store.finish(running["occurrence_id"])
    assert store.due(stamp(second)) == []


def test_restart_recovers_running(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    store.begin(delivery["occurrence_id"], "graph", "node")
    reopened = AgentScheduleStore(store.path)
    reopened.reset_running()
    assert reopened.begin(delivery["occurrence_id"], "graph", "node")["status"] == "running"


def test_concurrent_due_and_begin_claim_once(store, owner):
    item = create(store, owner)
    with ThreadPoolExecutor(max_workers=8) as pool:
        batches = list(pool.map(lambda _: store.due(stamp(item)), range(16)))
    assert len({batch[0]["occurrence_id"] for batch in batches}) == 1
    occurrence = batches[0][0]["occurrence_id"]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda _: store.begin(occurrence, "graph", "node"), range(16)))
    assert sum(claim is not None for claim in claims) == 1


def test_huge_interval_is_rejected(store, owner):
    with pytest.raises(ValueError, match="supported date range"):
        create(store, owner, interval_seconds=1e308)


def test_concurrent_idempotency(store, owner):
    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(lambda _: create(store, owner), range(16)))
    assert len({item["schedule_id"] for item in items}) == 1
    assert len(store.manage(owner, "list")["schedules"]) == 1


def test_cancelled_running_not_replayed_on_restart(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    store.begin(delivery["occurrence_id"], "graph", "node")
    store.manage(owner, "cancel", schedule_id=item["schedule_id"], expected_revision=1)
    store.reset_running()
    assert store.due(stamp(item, 1000)) == []


def test_stale_update_does_not_cancel_delivery(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    with pytest.raises(ValueError):
        store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=2, prompt="wrong")
    assert store.begin(delivery["occurrence_id"], "graph", "node") is not None


def test_finish_pending_failure_visible(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    store.finish(delivery["occurrence_id"], "failed")
    fetched = store.manage(owner, "get", schedule_id=item["schedule_id"])
    assert fetched["last_delivery_status"] == "failed"
    assert store.manage(owner, "list")["schedules"][0]["last_delivery_status"] == "failed"
    assert store.due(stamp(item)) == []


def test_prompt_update_keeps_pending_oneoff(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    updated = store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=1, prompt="updated prompt")
    assert updated["last_delivery_status"] == "pending"
    pending, = store.due(stamp(item, 100))
    assert pending["occurrence_id"] == delivery["occurrence_id"]
    assert pending["prompt"] == "updated prompt"
    assert store.begin(pending["occurrence_id"], "graph", "node") is not None


def test_pending_recurring_interval_can_be_cleared(store, owner):
    item = create(store, owner, interval_seconds=60)
    delivery, = store.due(stamp(item))
    revised = store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=1, interval_seconds=None)
    assert revised["status"] == "completed"
    store.finish(delivery["occurrence_id"])
    assert store.due(stamp(item, 1000)) == []


def test_pending_oneoff_can_become_recurring(store, owner):
    item = create(store, owner)
    delivery, = store.due(stamp(item))
    revised = store.manage(owner, "update", schedule_id=item["schedule_id"], expected_revision=1, interval_seconds=60)
    assert revised["status"] == "active"
    assert stamp(revised) == stamp(item, 60)
    store.finish(delivery["occurrence_id"])
    assert len(store.due(stamp(item, 60))) == 1
