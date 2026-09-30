"""Content addressed staging. The wire never accepts a filesystem path."""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import uuid
from pathlib import Path

from src.file_transaction import atomic_write_text, run_with_interprocess_lock

CHUNK_SIZE = 256 * 1024


def encode(value) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


def file_digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return run_with_interprocess_lock(str(path) + ".json.lock",
        lambda: json.loads(path.read_text(encoding="utf-8")) if path.exists() else default)


def write_json(path: Path, value):
    run_with_interprocess_lock(str(path) + ".json.lock",
        lambda: atomic_write_text(str(path), encode(value)))


class BlobStore:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)

    def path(self, sha: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{64}", sha):
            raise ValueError("invalid blob digest")
        return self.root / sha

    def put_file(self, source: Path) -> tuple[str, int]:
        temporary = self.root / (uuid.uuid4().hex + ".tmp")
        try:
            shutil.copyfile(source, temporary)
            sha = file_digest(temporary)
            size = temporary.stat().st_size
            path = self.path(sha)
            def publish():
                if path.exists():
                    if file_digest(path) != sha:
                        raise ValueError("cached blob checksum mismatch")
                else:
                    os.replace(temporary, path)
            run_with_interprocess_lock(str(path.with_suffix(".lock")), publish)
            return sha, size
        finally:
            temporary.unlink(missing_ok=True)

    def put_json(self, value) -> str:
        sha = digest(value)
        path = self.path(sha)
        def publish():
            if path.exists():
                if file_digest(path) != sha:
                    raise ValueError("cached manifest checksum mismatch")
            else:
                write_json(path, value)
        run_with_interprocess_lock(str(path.with_suffix(".lock")), publish)
        return sha

    def status(self, sha: str) -> dict:
        path = self.path(sha)
        if path.exists():
            if file_digest(path) != sha:
                raise ValueError("staged blob checksum mismatch")
            return {"complete": True, "offset": path.stat().st_size}
        partial = path.with_suffix(".partial")
        return {"complete": False, "offset": partial.stat().st_size if partial.exists() else 0}

    def read(self, sha: str, offset: int) -> dict:
        path = self.path(sha)
        if offset < 0 or offset > path.stat().st_size:
            raise ValueError("invalid chunk offset")
        with path.open("rb") as stream:
            stream.seek(offset)
            data = stream.read(CHUNK_SIZE)
        return {"offset": offset, "total": path.stat().st_size,
                "data": base64.b64encode(data).decode("ascii")}

    def write(self, sha: str, chunk) -> dict:
        path = self.path(sha)
        data = base64.b64decode(chunk.data, validate=True)
        if len(data) > CHUNK_SIZE or chunk.offset + len(data) > chunk.total:
            raise ValueError("invalid chunk size")
        def apply():
            status = self.status(sha)
            if status["complete"]:
                if status["offset"] != chunk.total:
                    raise ValueError("blob size mismatch")
                return status
            partial = path.with_suffix(".partial")
            if chunk.offset != status["offset"]:
                raise ValueError("chunk offset changed; resume from acknowledged offset")
            with partial.open("ab") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            if partial.stat().st_size == chunk.total:
                if file_digest(partial) != sha:
                    partial.unlink()
                    raise ValueError("blob checksum mismatch; upload discarded")
                os.replace(partial, path)
            return self.status(sha)
        return run_with_interprocess_lock(str(path.with_suffix(".lock")), apply)
