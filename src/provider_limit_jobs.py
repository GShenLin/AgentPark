from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime
from typing import Any

from src.provider_limit_probe import run_provider_limit_tests
from src.provider_model_discovery import run_provider_model_discovery
from src.provider_limit_schema import read_provider_limit_file


class ProviderLimitJobStore:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, Any]] = {}

    def start(self, *, timeout_seconds: float) -> dict[str, Any]:
        return self._start_job(kind="limit_test", timeout_seconds=timeout_seconds)

    def start_model_discovery(self, *, timeout_seconds: float) -> dict[str, Any]:
        return self._start_job(kind="model_refresh", timeout_seconds=timeout_seconds)

    def _start_job(self, *, kind: str, timeout_seconds: float) -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        job = {
            "job_id": job_id,
            "kind": kind,
            "status": "running",
            "started_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "finished_at": "",
            "provider_id": "",
            "index": 0,
            "total": 0,
            "error": "",
            "result": None,
        }
        with self._lock:
            self._jobs[job_id] = job

        thread = threading.Thread(
            target=self._run_job,
            args=(job_id, kind, float(timeout_seconds)),
            daemon=True,
            name=f"provider-{kind}-{job_id[:8]}",
        )
        thread.start()
        return self.get(job_id)

    def get(self, job_id: str) -> dict[str, Any]:
        with self._lock:
            job = dict(self._jobs.get(str(job_id or "").strip()) or {})
        if not job:
            return {"job_id": str(job_id or ""), "status": "not_found"}
        return job

    def latest_running(self) -> dict[str, Any] | None:
        with self._lock:
            jobs = [dict(job) for job in self._jobs.values() if job.get("status") == "running"]
        if not jobs:
            return None
        jobs.sort(key=lambda item: str(item.get("started_at") or ""), reverse=True)
        return jobs[0]

    def _run_job(self, job_id: str, kind: str, timeout_seconds: float) -> None:
        started = time.monotonic()

        def on_progress(payload: dict[str, Any]) -> None:
            with self._lock:
                job = self._jobs.get(job_id)
                if not isinstance(job, dict):
                    return
                job["provider_id"] = str(payload.get("provider_id") or "")
                job["index"] = int(payload.get("index") or 0)
                job["total"] = int(payload.get("total") or 0)

        try:
            runner = run_provider_model_discovery if kind == "model_refresh" else run_provider_limit_tests
            result = runner(timeout_seconds=timeout_seconds, progress_callback=on_progress)
        except Exception as exc:
            with self._lock:
                job = self._jobs.get(job_id)
                if isinstance(job, dict):
                    job["status"] = "failed"
                    job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                    job["duration_ms"] = int((time.monotonic() - started) * 1000)
                    job["error"] = f"{type(exc).__name__}: {exc}"
            return

        with self._lock:
            job = self._jobs.get(job_id)
            if isinstance(job, dict):
                job["status"] = "finished"
                job["finished_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                job["duration_ms"] = int((time.monotonic() - started) * 1000)
                job["result"] = result

    def read_result(self) -> dict[str, Any]:
        return read_provider_limit_file()
