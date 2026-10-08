from concurrent.futures import ThreadPoolExecutor
from datetime import datetime

import pytest

from src.cron.repository import CronRepository
from src.cron.schedule import CreateJob, UpdateJob, next_deadline, schedule_adapter


def create(repo, *, node="agent", name="check", now=1000, schedule=None):
    return repo.create(node, CreateJob.model_validate({"name": name, "prompt": "Check changes",
        "schedule": schedule or {"kind": "every", "seconds": 60}}), "developer", now)


def update(repo, job, now=1060, **changes):
    return repo.update(job["node_id"], UpdateJob.model_validate({"job_id": job["id"],
        "expected_revision": job["revision"], **changes}), "developer", now)


def test_concurrent_create_is_idempotent_and_node_scoped(tmp_path):
    repo = CronRepository(tmp_path)
    with ThreadPoolExecutor(4) as pool:
        jobs = list(pool.map(lambda _: create(CronRepository(tmp_path)), range(8)))
    assert len({j["id"] for j in jobs}) == 1
    assert create(repo, node="other")["id"] != jobs[0]["id"]
    with pytest.raises(ValueError, match="current node"):
        repo.delete("other", jobs[0]["id"], 1, 1000)
    with pytest.raises(ValueError, match="name already exists"):
        create(repo, schedule={"kind": "every", "seconds": 120})


def test_overdue_recurring_runs_coalesce_without_active_backlog(tmp_path):
    repo = CronRepository(tmp_path)
    job = create(repo)
    repo.materialize_due(10000)
    assert len(repo.pending_runs()) == 1
    assert repo.list("agent")["jobs"][0]["next_run"] == 10060
    run = repo.pending_runs()[0]
    repo.materialize_due(10180)
    assert len(repo.pending_runs()) == 1
    assert repo.begin_run(run["id"], "agent", 10180)
    repo.materialize_due(10300)
    assert repo.pending_runs() == []
    repo.finish_run(run["id"], 10301)
    repo.materialize_due(10360)
    assert len(repo.pending_runs()) == 1
    assert repo.pending_runs()[0]["job_id"] == job["id"]


def test_single_run_survives_restart_and_is_acknowledged_once(tmp_path):
    repo = CronRepository(tmp_path)
    job = create(repo, schedule={"kind": "at", "at": "1970-01-01T00:20:00+00:00"})
    repo.materialize_due(1300)
    run = repo.pending_runs()[0]
    assert not repo.list("agent")["jobs"][0]["enabled"]
    assert create(repo, now=1400, schedule=job["schedule"])["id"] == job["id"]
    assert repo.begin_run(run["id"], "other", 1300) is None
    assert repo.begin_run(run["id"], "agent", 1300)
    restarted = CronRepository(tmp_path)
    restarted.recover_interrupted()
    assert restarted.pending_runs()[0]["id"] == run["id"]
    assert restarted.begin_run(run["id"], "agent", 1400)
    restarted.finish_run(run["id"], 1401)
    restarted.recover_interrupted()
    restarted.materialize_due(2000)
    assert restarted.pending_runs() == []
    assert restarted.begin_run(run["id"], "agent", 2000) is None


@pytest.mark.parametrize("action", ["pause", "delete", "reschedule"])
def test_cancel_after_enqueue_prevents_start(tmp_path, action):
    repo = CronRepository(tmp_path)
    job = create(repo)
    repo.materialize_due(1060)
    run = repo.pending_runs()[0]
    if action == "delete":
        repo.delete("agent", job["id"], 1, 1061)
    elif action == "pause":
        update(repo, job, enabled=False)
    else:
        update(repo, job, schedule={"kind": "every", "seconds": 120})
    assert repo.begin_run(run["id"], "agent", 1062) is None
    assert repo.list("agent")["recent_runs"][0]["status"] == "cancelled"


def test_edit_preserves_pending_one_shot_and_cannot_elevate_access(tmp_path):
    repo = CronRepository(tmp_path)
    job = create(repo, schedule={"kind": "at", "at": "1970-01-01T00:20:00+00:00"})
    repo.materialize_due(1300)
    job = repo.update("agent", UpdateJob(job_id=job["id"], expected_revision=1, prompt="New prompt"), "nondeveloper", 1300)
    job = update(repo, job, now=1301, name="Renamed")
    run = repo.pending_runs()[0]
    assert run["prompt"] == "New prompt"
    assert run["access_role"] == job["access_role"] == "nondeveloper"
    with pytest.raises(ValueError, match="revision conflict"):
        repo.update("agent", UpdateJob(job_id=job["id"], expected_revision=1, enabled=False), "developer", 1302)


def test_pause_does_not_cancel_running_and_resume_rebases_interval(tmp_path):
    repo = CronRepository(tmp_path)
    job = create(repo)
    repo.materialize_due(1060)
    run = repo.pending_runs()[0]
    repo.begin_run(run["id"], "agent", 1060)
    job = update(repo, job, enabled=False)
    assert repo.list("agent")["recent_runs"][0]["status"] == "running"
    job = update(repo, job, now=10000, enabled=True)
    assert job["next_run"] == 10060
    repo.finish_run(run["id"], 10001, "Provider failed")
    assert repo.list("agent")["recent_runs"][0]["status"] == "failed"
    repo.materialize_due(10060)
    assert len(repo.pending_runs()) == 1


def test_timezone_cron_and_invalid_contracts():
    schedule = schedule_adapter.validate_python({"kind": "cron", "expression": "0 9 * * 1-5", "timezone": "Asia/Shanghai"})
    now = datetime.fromisoformat("2026-10-09T09:01:00+08:00").timestamp()
    assert next_deadline(schedule, now) == datetime.fromisoformat("2026-10-12T09:00:00+08:00").timestamp()
    for value in [
        {"kind": "at", "at": "2030-01-02T09:00:00"},
        {"kind": "every", "seconds": "60"},
        {"kind": "every", "seconds": True},
        {"kind": "every", "seconds": 0},
        {"kind": "every", "seconds": 60, "node_id": "other"},
        {"kind": "cron", "expression": "* * * * * *", "timezone": "Asia/Shanghai"},
    ]:
        with pytest.raises(ValueError):
            schedule_adapter.validate_python(value)


def test_single_run_rescheduled_during_execution_waits_for_previous_run(tmp_path):
    repo = CronRepository(tmp_path)
    job = create(repo)
    repo.materialize_due(1060)
    run = repo.pending_runs()[0]
    repo.begin_run(run["id"], "agent", 1060)
    update(repo, job, schedule={"kind": "at", "at": "1970-01-01T00:20:00Z"})
    repo.materialize_due(1300)
    assert repo.list("agent")["jobs"][0]["enabled"]
    repo.finish_run(run["id"], 1301)
    repo.materialize_due(1302)
    assert len(repo.pending_runs()) == 1
    assert repo.pending_runs()[0]["scheduled_at"] == 1200


def test_past_or_impossible_schedules_are_rejected(tmp_path):
    repo = CronRepository(tmp_path)
    with pytest.raises(ValueError, match="future"):
        create(repo, schedule={"kind": "at", "at": "1970-01-01T00:01:00Z"})
    with pytest.raises(ValueError):
        create(repo, schedule={"kind": "cron", "expression": "0 0 31 2 *", "timezone": "UTC"})
    assert repo.list("agent")["jobs"] == []
