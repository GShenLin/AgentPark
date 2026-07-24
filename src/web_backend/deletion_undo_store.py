from __future__ import annotations

import json
import os
import re
import shutil
import threading
import uuid
from datetime import datetime, timezone
from typing import Any

from src.file_transaction import atomic_write_text
from src.workspace_settings import read_undo_settings

from . import runtime_paths


_TOKEN_RE = re.compile(r"^[a-f0-9]{32}$")


class DeletionUndoStore:
    def __init__(self) -> None:
        self._lock = threading.RLock()

    def max_steps(self) -> int:
        return int(read_undo_settings()["max_steps"])

    def begin(self, kind: str, metadata: dict[str, Any]) -> dict[str, Any] | None:
        if self.max_steps() <= 0:
            return None
        token = uuid.uuid4().hex
        root = self._root_dir()
        os.makedirs(root, exist_ok=True)
        temp_dir = os.path.join(root, f".tmp-{token}")
        os.makedirs(temp_dir)
        return {
            "token": token,
            "kind": str(kind or "").strip(),
            "metadata": dict(metadata or {}),
            "temp_dir": temp_dir,
            "entry_dir": os.path.join(root, token),
        }

    def archive_directory(self, entry: dict[str, Any], source_dir: str, name: str) -> str:
        target = os.path.join(str(entry["temp_dir"]), name)
        shutil.move(source_dir, target)
        return target

    def write_json(self, entry: dict[str, Any], name: str, payload: object) -> str:
        path = os.path.join(str(entry["temp_dir"]), name)
        atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
        return path

    def write_bytes(self, entry: dict[str, Any], name: str, payload: bytes) -> str:
        path = os.path.join(str(entry["temp_dir"]), name)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "wb") as handle:
            handle.write(payload)
        return path

    def commit(self, entry: dict[str, Any]) -> str:
        token = str(entry["token"])
        metadata = {
            "token": token,
            "kind": str(entry["kind"]),
            "created_at": datetime.now(timezone.utc).isoformat(),
            **dict(entry.get("metadata") or {}),
        }
        with self._lock:
            self.write_json(entry, "metadata.json", metadata)
            os.replace(str(entry["temp_dir"]), str(entry["entry_dir"]))
            try:
                self._trim_locked()
            except OSError:
                pass
        return token

    def discard(self, entry: dict[str, Any] | None) -> None:
        if not entry:
            return
        shutil.rmtree(str(entry.get("temp_dir") or ""), ignore_errors=True)

    def load(self, token: str) -> tuple[dict[str, Any], str]:
        safe_token = self._safe_token(token)
        with self._lock:
            self._trim_locked()
            entry_dir = os.path.join(self._root_dir(), safe_token)
            metadata_path = os.path.join(entry_dir, "metadata.json")
            if not os.path.isfile(metadata_path):
                raise FileNotFoundError("undo entry not found or expired")
            with open(metadata_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
            if not isinstance(metadata, dict):
                raise ValueError("undo metadata must be an object")
            return metadata, entry_dir

    def consume(self, token: str) -> None:
        safe_token = self._safe_token(token)
        with self._lock:
            shutil.rmtree(os.path.join(self._root_dir(), safe_token))

    def _trim_locked(self) -> None:
        root = self._root_dir()
        if not os.path.isdir(root):
            return
        max_steps = self.max_steps()
        entries: list[tuple[int, str]] = []
        for name in os.listdir(root):
            path = os.path.join(root, name)
            if name.startswith(".tmp-"):
                continue
            if not _TOKEN_RE.fullmatch(name) or not os.path.isdir(path):
                continue
            try:
                created = os.stat(os.path.join(path, "metadata.json")).st_mtime_ns
            except OSError:
                created = os.stat(path).st_mtime_ns
            entries.append((created, path))
        entries.sort(reverse=True)
        for _, path in entries[max_steps:]:
            shutil.rmtree(path, ignore_errors=True)

    def _root_dir(self) -> str:
        return os.path.join(runtime_paths._get_runtime_root(), ".cache", "undo")

    @staticmethod
    def _safe_token(token: str) -> str:
        safe_token = str(token or "").strip().lower()
        if not _TOKEN_RE.fullmatch(safe_token):
            raise ValueError("invalid undo token")
        return safe_token


deletion_undo_store = DeletionUndoStore()


__all__ = ["DeletionUndoStore", "deletion_undo_store"]
