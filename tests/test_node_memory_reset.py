from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
import threading

from src.task_direction_store import TaskDirectionStore
from src.task_direction_store import task_direction_path
from src.web_backend.node_cancellation import NodeCancellationRegistry
from src.web_backend.node_memory_reset import reset_node_memory


def _direction_state() -> dict:
    return {
        "objective": "Old task",
        "hypotheses": [],
        "evidence": [],
        "unresolved_risks": [],
        "done_criteria": [
            {
                "id": "done",
                "statement": "Finish old task",
                "status": "pending",
                "evidence_ids": [],
            }
        ],
    }


def test_reset_waits_for_active_work_before_clearing_task_state(tmp_path):
    config_path = tmp_path / "config.json"
    memory_path = tmp_path / "memory.md"
    messages_path = tmp_path / "messages.jsonl"
    config_path.write_text(
        json.dumps(
            {
                "state": "working",
                "pending": [],
                "pending_count": 0,
                "inflight": {"trace_id": "task-running"},
            }
        ),
        encoding="utf-8",
    )
    memory_path.write_text("old memory", encoding="utf-8")
    messages_path.write_text("old messages", encoding="utf-8")
    direction_path = task_direction_path(str(tmp_path), "task-running")
    TaskDirectionStore(direction_path, task_id="task-running").replace(
        expected_revision=0,
        state=_direction_state(),
    )

    registry = NodeCancellationRegistry()
    active_event = registry.begin(str(config_path))

    def finish_active_run() -> None:
        active_event.wait(timeout=2.0)
        registry.end(str(config_path), active_event)

    worker = threading.Thread(target=finish_active_run)
    worker.start()
    result = reset_node_memory(
        core=SimpleNamespace(node_cancellations=registry, node_runs={}),
        config_path=str(config_path),
        memory_path=str(memory_path),
        messages_path=str(messages_path),
        node_directory=str(tmp_path),
    )
    worker.join(timeout=2.0)

    assert active_event.is_set()
    assert result.active_runs_cancelled == 1
    assert memory_path.read_text(encoding="utf-8") == ""
    assert messages_path.read_text(encoding="utf-8") == ""
    assert not Path(direction_path).exists()
