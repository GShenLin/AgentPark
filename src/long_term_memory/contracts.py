from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Protocol


class MemoryContractError(ValueError):
    pass


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def digest(value: object) -> str:
    return hashlib.sha256(encode(value).encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class Source:
    id: str
    trace_id: str
    updated_at: float
    records: tuple[dict, ...]
    complete: bool

    @property
    def fingerprint(self) -> str:
        return digest(self.records)


@dataclass(frozen=True)
class Extraction:
    rollout_summary: str
    rollout_slug: str

    @classmethod
    def parse(cls, text: str) -> "Extraction":
        data = strict_object(text, {"rollout_summary", "rollout_slug"})
        summary, slug = data["rollout_summary"], data["rollout_slug"]
        if bool(summary.strip()) != bool(slug.strip()):
            raise MemoryContractError("empty extraction must have two empty fields")
        if len(summary.encode("utf-8")) > 9000 or len(slug) > 100:
            raise MemoryContractError("extraction exceeds output budget")
        return cls(summary.strip(), slug.strip())


@dataclass(frozen=True)
class Consolidation:
    memory_summary: str
    source_ids: tuple[str, ...]

    @classmethod
    def parse(cls, text: str, available: set[str]) -> "Consolidation":
        data = strict_object(text, {"memory_summary", "source_ids"}, strings=False)
        summary, ids = data["memory_summary"], data["source_ids"]
        if not isinstance(summary, str) or not isinstance(ids, list):
            raise MemoryContractError("consolidation requires string summary and list source_ids")
        if any(not isinstance(item, str) for item in ids) or len(set(ids)) != len(ids):
            raise MemoryContractError("source_ids must be unique strings")
        if not set(ids) <= available:
            raise MemoryContractError("consolidation contains unknown source ids")
        if len(summary.encode("utf-8")) > 10000 or not summary.startswith("v1\n"):
            raise MemoryContractError("summary must start with v1 and fit 10000 UTF-8 bytes")
        for heading in ("## User Profile", "## User preferences", "## General Tips", "## What's in Memory"):
            if heading not in summary:
                raise MemoryContractError(f"missing summary section: {heading}")
        import re
        pointers = set(re.findall(r"memory:([a-f0-9]{64})", summary))
        if pointers != set(ids):
            raise MemoryContractError("summary memory pointers must match source_ids exactly")
        return cls(summary.strip(), tuple(ids))


def strict_object(text: str, keys: set[str], *, strings: bool = True) -> dict:
    if not isinstance(text, str):
        raise MemoryContractError("model output must be JSON text")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise MemoryContractError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    data = json.loads(text, object_pairs_hook=unique)
    if not isinstance(data, dict) or set(data) != keys:
        raise MemoryContractError(f"expected exactly these fields: {sorted(keys)}")
    if strings and any(not isinstance(v, str) for v in data.values()):
        raise MemoryContractError("extraction fields must be strings")
    return data


class MemoryModel(Protocol):
    """An isolated, tool-free model request; failures must propagate to job state."""

    def complete(self, phase: str, instructions: str, payload: dict) -> str: ...
