from __future__ import annotations

import json
import os
import subprocess
import threading
from pathlib import Path
from typing import Any


class EventJournal:
    """Durably append benchmark events so process loss does not erase evidence."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            raise FileExistsError(f"Benchmark event journal already exists: {self.path}")

    def append(self, record: dict[str, Any]) -> None:
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self._lock:
            with self.path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(encoded)


def rewrite_event_journal(path: Path, records: list[dict[str, Any]]) -> None:
    """Atomically rebuild a journal from the authoritative result payload."""

    if not all(isinstance(record, dict) for record in records):
        raise TypeError("Benchmark event journal records must be objects.")
    temporary = path.with_name(f"{path.name}.repair.tmp")
    if temporary.exists():
        raise FileExistsError(f"Benchmark journal repair file already exists: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n")
    os.replace(temporary, path)


def require_empty_result_dir(path: Path) -> None:
    if path.exists() and any(path.iterdir()):
        raise FileExistsError(
            f"Benchmark result directory must be empty to prevent session/result reuse: {path}"
        )
    path.mkdir(parents=True, exist_ok=True)


def resolve_agent_profile(raw: str, *, project_root: Path) -> Path:
    candidate = Path(raw).expanduser()
    if candidate.is_file():
        return candidate.resolve()
    profile_id = str(raw or "").strip()
    if not profile_id:
        raise ValueError("Agent benchmark requires a profile path or profile id.")
    profile_name = profile_id if profile_id.lower().endswith(".json") else f"{profile_id}.json"
    project_candidate = project_root / "agent" / profile_name
    if project_candidate.is_file():
        return project_candidate.resolve()
    raise FileNotFoundError(
        f"Agent profile not found as a path or under {project_root / 'agent'}: {raw}"
    )


def git_workspace_snapshot(workspace: Path) -> dict[str, Any]:
    revision = _git(workspace, "rev-parse", "HEAD", required=True).strip()
    status_text = _git(
        workspace,
        "status",
        "--porcelain=v1",
        "--untracked-files=all",
        required=True,
    )
    status = [line for line in status_text.splitlines() if line]
    return {
        "revision": revision,
        "clean": not status,
        "status": status,
        "changed_paths": [line[3:] for line in status if len(line) >= 4],
    }


def _git(workspace: Path, *args: str, required: bool) -> str:
    process = subprocess.run(
        ["git", "-C", str(workspace), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    stdout = process.stdout.decode("utf-8", errors="strict")
    stderr = process.stderr.decode("utf-8", errors="replace").strip()
    if process.returncode != 0 and required:
        raise RuntimeError(f"git {' '.join(args)} failed for {workspace}: {stderr}")
    return stdout
