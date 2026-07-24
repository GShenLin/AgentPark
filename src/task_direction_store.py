from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
import shutil
from typing import Any

from src.file_transaction import atomic_write_text
from src.file_transaction import run_with_interprocess_lock
from src.task_direction_models import TASK_DIRECTION_SCHEMA_VERSION
from src.task_direction_models import TaskDirectionContractError
from src.task_direction_models import TaskDirectionState
from src.task_direction_update import TaskDirectionUpdate


TASK_DIRECTION_FILENAME = "task_direction.json"
TASK_DIRECTION_TASKS_DIRECTORY = "tasks"
TASK_DIRECTION_STATUS_ACTIVE = "active"
TASK_DIRECTION_STATUS_COMPLETED = "completed"
_TASK_DIRECTION_STATUSES = {
    TASK_DIRECTION_STATUS_ACTIVE,
    TASK_DIRECTION_STATUS_COMPLETED,
}
_LEGACY_ANALYSIS_ARTIFACTS = (
    "analysis_verification.json",
    "analysis_report.md",
    "analysis_report_appendix.md",
    TASK_DIRECTION_FILENAME,
)


class TaskDirectionRevisionConflict(RuntimeError):
    """Raised when an update is based on a stale task direction revision."""


@dataclass(frozen=True)
class StoredTaskDirection:
    task_id: str
    status: str
    revision: int
    updated_at: str
    state: TaskDirectionState

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": TASK_DIRECTION_SCHEMA_VERSION,
            "task_id": self.task_id,
            "status": self.status,
            "revision": self.revision,
            "updated_at": self.updated_at,
            "state": self.state.to_payload(),
        }


class TaskDirectionStore:
    def __init__(self, path: str, *, task_id: str) -> None:
        raw_path = str(path or "").strip()
        if not raw_path:
            raise TaskDirectionContractError("task direction store path is required")
        self.task_id = _required_task_id(task_id)
        self.path = os.path.abspath(raw_path)

    @classmethod
    def for_agent(cls, agent: object) -> "TaskDirectionStore":
        memory_path = str(getattr(agent, "current_memory_path", "") or "").strip()
        if not memory_path:
            memory = getattr(agent, "memory", None)
            memory_path = str(getattr(memory, "current_memory_path", "") or "").strip()
        if not memory_path:
            raise TaskDirectionContractError(
                "task direction tools require an agent with a configured memory path"
            )
        task_id = str(getattr(agent, "_agentpark_task_id", "") or "").strip()
        if not task_id:
            raise TaskDirectionContractError(
                "task direction tools require an agent bound to a task_id"
            )
        node_directory = os.path.dirname(os.path.abspath(memory_path))
        return cls(task_direction_path(node_directory, task_id), task_id=task_id)

    def read(self) -> StoredTaskDirection | None:
        if not os.path.isfile(self.path):
            return None
        with open(self.path, "r", encoding="utf-8") as handle:
            payload = json.load(handle)
        stored = self._parse_stored_payload(payload)
        if stored.task_id != self.task_id:
            raise TaskDirectionContractError(
                "task_direction.json task_id does not match the current task"
            )
        return stored

    def replace(self, *, expected_revision: int, state: object) -> StoredTaskDirection:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 0:
            raise TaskDirectionContractError("expected_revision must be a non-negative integer")
        parsed_state = TaskDirectionState.from_payload(state)
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

        def write() -> StoredTaskDirection:
            current = self.read()
            current_revision = current.revision if current is not None else 0
            if current_revision != expected_revision:
                raise TaskDirectionRevisionConflict(
                    f"task direction revision conflict: expected {expected_revision}, current {current_revision}"
                )
            if current is not None and current.status == TASK_DIRECTION_STATUS_COMPLETED:
                raise TaskDirectionContractError("completed task direction cannot be replaced")
            if current is not None:
                raise TaskDirectionContractError(
                    "task direction is already initialized; use an incremental update"
                )
            stored = StoredTaskDirection(
                task_id=self.task_id,
                status=TASK_DIRECTION_STATUS_ACTIVE,
                revision=current_revision + 1,
                updated_at=datetime.now().astimezone().isoformat(),
                state=parsed_state,
            )
            self._write(stored)
            return stored

        return run_with_interprocess_lock(self.path + ".lock", write)

    def update(self, *, expected_revision: int, update: object) -> tuple[StoredTaskDirection, TaskDirectionUpdate]:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision <= 0:
            raise TaskDirectionContractError("expected_revision must be a positive integer")

        def write() -> tuple[StoredTaskDirection, TaskDirectionUpdate]:
            current = self.read()
            if current is None:
                raise TaskDirectionContractError("task direction must be initialized before update")
            if current.revision != expected_revision:
                raise TaskDirectionRevisionConflict(
                    f"task direction revision conflict: expected {expected_revision}, current {current.revision}"
                )
            if current.status == TASK_DIRECTION_STATUS_COMPLETED:
                raise TaskDirectionContractError("completed task direction cannot be updated")
            parsed_update = TaskDirectionUpdate.from_payload(update, current_state=current.state)
            stored = StoredTaskDirection(
                task_id=self.task_id,
                status=TASK_DIRECTION_STATUS_ACTIVE,
                revision=current.revision + 1,
                updated_at=datetime.now().astimezone().isoformat(),
                state=parsed_update.state,
            )
            self._write(stored)
            return stored, parsed_update

        return run_with_interprocess_lock(self.path + ".lock", write)

    def complete(self, *, expected_revision: int) -> StoredTaskDirection:
        return self.complete_with_state(expected_revision=expected_revision, state=None)

    def complete_with_state(
        self,
        *,
        expected_revision: int,
        state: object | None,
    ) -> StoredTaskDirection:
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision <= 0:
            raise TaskDirectionContractError("expected_revision must be a positive integer")
        parsed_state = TaskDirectionState.from_payload(state) if state is not None else None

        def write() -> StoredTaskDirection:
            current = self.read()
            if current is None:
                raise TaskDirectionContractError("task direction must be initialized before completion")
            if current.revision != expected_revision:
                raise TaskDirectionRevisionConflict(
                    f"task direction revision conflict: expected {expected_revision}, current {current.revision}"
                )
            if current.status == TASK_DIRECTION_STATUS_COMPLETED:
                if parsed_state is not None and current.state != parsed_state:
                    raise TaskDirectionContractError(
                        "completed task direction cannot be replaced during completion"
                    )
                return current
            stored = StoredTaskDirection(
                task_id=self.task_id,
                status=TASK_DIRECTION_STATUS_COMPLETED,
                revision=current.revision + 1,
                updated_at=datetime.now().astimezone().isoformat(),
                state=parsed_state or current.state,
            )
            self._write(stored)
            return stored

        return run_with_interprocess_lock(self.path + ".lock", write)

    def _write(self, stored: StoredTaskDirection) -> None:
        atomic_write_text(
            self.path,
            json.dumps(stored.to_payload(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    @staticmethod
    def _parse_stored_payload(payload: object) -> StoredTaskDirection:
        if not isinstance(payload, dict):
            raise TaskDirectionContractError("task_direction.json must contain an object")
        allowed = {"schema_version", "task_id", "status", "revision", "updated_at", "state"}
        unknown = sorted(set(payload) - allowed)
        if unknown:
            raise TaskDirectionContractError(
                f"task_direction.json has unknown fields: {', '.join(unknown)}"
            )
        if payload.get("schema_version") != TASK_DIRECTION_SCHEMA_VERSION:
            raise TaskDirectionContractError(
                f"unsupported task direction schema_version: {payload.get('schema_version')!r}"
            )
        task_id = _required_task_id(payload.get("task_id"))
        status = str(payload.get("status") or "").strip()
        if status not in _TASK_DIRECTION_STATUSES:
            raise TaskDirectionContractError(
                "task_direction.json status must be one of: active, completed"
            )
        revision = payload.get("revision")
        if isinstance(revision, bool) or not isinstance(revision, int) or revision <= 0:
            raise TaskDirectionContractError("task_direction.json revision must be a positive integer")
        updated_at = str(payload.get("updated_at") or "").strip()
        if not updated_at:
            raise TaskDirectionContractError("task_direction.json updated_at is required")
        return StoredTaskDirection(
            task_id=task_id,
            status=status,
            revision=revision,
            updated_at=updated_at,
            state=TaskDirectionState.from_payload(payload.get("state")),
        )


def task_direction_path(node_directory: str, task_id: str) -> str:
    node_dir = _required_node_directory(node_directory)
    normalized_task_id = _required_task_id(task_id)
    digest = hashlib.sha256(normalized_task_id.encode("utf-8")).hexdigest()
    return os.path.join(
        node_dir,
        TASK_DIRECTION_TASKS_DIRECTORY,
        f"task_{digest}",
        TASK_DIRECTION_FILENAME,
    )


def archive_legacy_task_artifacts(node_directory: str) -> list[str]:
    node_dir = _required_node_directory(node_directory)
    legacy_direction = os.path.join(node_dir, TASK_DIRECTION_FILENAME)
    if not os.path.isfile(legacy_direction):
        return []

    def migrate() -> list[str]:
        if not os.path.isfile(legacy_direction):
            return []
        with open(legacy_direction, "rb") as handle:
            digest = hashlib.sha256(handle.read()).hexdigest()[:16]
        destination = os.path.join(
            node_dir,
            TASK_DIRECTION_TASKS_DIRECTORY,
            f"legacy_{digest}",
        )
        os.makedirs(destination, exist_ok=True)
        moved: list[str] = []
        for filename in _LEGACY_ANALYSIS_ARTIFACTS:
            source = os.path.join(node_dir, filename)
            if not os.path.isfile(source):
                continue
            target = os.path.join(destination, filename)
            if os.path.exists(target):
                raise TaskDirectionContractError(
                    f"legacy task artifact destination already exists: {target}"
                )
            shutil.move(source, target)
            moved.append(target)
        return moved

    return run_with_interprocess_lock(legacy_direction + ".lock", migrate)


def clear_task_direction_states(node_directory: str) -> list[str]:
    node_dir = _required_node_directory(node_directory)
    candidates = [os.path.join(node_dir, TASK_DIRECTION_FILENAME)]
    tasks_root = os.path.join(node_dir, TASK_DIRECTION_TASKS_DIRECTORY)
    if os.path.isdir(tasks_root):
        for entry in os.scandir(tasks_root):
            if entry.is_dir(follow_symlinks=False):
                candidates.append(os.path.join(entry.path, TASK_DIRECTION_FILENAME))

    removed: list[str] = []
    for path in candidates:
        for target in (path, path + ".lock"):
            if not os.path.isfile(target):
                continue
            os.remove(target)
            removed.append(target)
    return removed


def _required_task_id(value: object) -> str:
    task_id = str(value or "").strip()
    if not task_id:
        raise TaskDirectionContractError("task_id must be a non-empty string")
    if len(task_id) > 512:
        raise TaskDirectionContractError("task_id cannot exceed 512 characters")
    return task_id


def _required_node_directory(value: object) -> str:
    raw_path = str(value or "").strip()
    if not raw_path:
        raise TaskDirectionContractError("task direction node directory is required")
    return os.path.abspath(raw_path)
