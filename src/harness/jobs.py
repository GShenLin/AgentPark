"""Background installation jobs with explicit failures and per-Harness exclusion."""
from __future__ import annotations

from copy import deepcopy
import threading
import uuid

from .install_manager import mutate_installation
from .registry import descriptor


class HarnessJobs:
    def __init__(self):
        self._lock = threading.Lock()
        self._jobs: dict[str, dict] = {}

    def list(self) -> list[dict]:
        with self._lock:
            return deepcopy(list(self._jobs.values()))

    def get(self, job_id: str) -> dict:
        with self._lock:
            return deepcopy(self._jobs[job_id])

    def start(self, harness_id: str, action: str) -> dict:
        descriptor(harness_id)
        if action not in {"install", "upgrade", "uninstall"}:
            raise ValueError("Harness action must be install, upgrade or uninstall.")
        with self._lock:
            if any(job["harness_id"] == harness_id and job["status"] == "running" for job in self._jobs.values()):
                raise RuntimeError("A Harness installation job is already running.")
            # Retain the latest operation for each Harness, preventing unbounded job history.
            self._jobs = {key: value for key, value in self._jobs.items() if value["harness_id"] != harness_id}
            job = {"id": uuid.uuid4().hex, "harness_id": harness_id, "action": action,
                   "status": "running", "error": "", "output": ""}
            self._jobs[job["id"]] = job
            snapshot = deepcopy(job)
        threading.Thread(target=self._run, args=(job,), name=f"harness-{action}-{harness_id}", daemon=True).start()
        return snapshot

    def _run(self, job: dict) -> None:
        try:
            result = mutate_installation(job["harness_id"], job["action"])
            update = {"status": "completed", **result}
        except Exception as exc:
            update = {"status": "failed", "error": f"{type(exc).__name__}: {exc}"}
        with self._lock:
            job.update(update)
