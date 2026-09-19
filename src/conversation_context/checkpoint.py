from __future__ import annotations

import hashlib
import json
from pathlib import Path

from src.file_transaction import atomic_write_text

FILENAME = "conversation_checkpoint.json"


def encode(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def estimate_tokens(value: object) -> int:
    """Same UTF-8 / 4 estimate as session compaction; not billed or tokenizer-exact tokens."""
    return (len(encode(value).encode("utf-8")) + 3) // 4


def fingerprint(records: list[dict]) -> str:
    return hashlib.sha256(encode(records).encode("utf-8")).hexdigest()


def load_checkpoint(directory: Path, records: list[dict]) -> tuple[int, str]:
    path = directory / FILENAME
    if not path.exists():
        return 0, ""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or set(data) != {"version", "covered", "fingerprint", "summary"}:
        raise ValueError(f"invalid conversation checkpoint: {path}")
    count = data["covered"]
    if data["version"] != 1 or type(count) is not int or count < 1 or not isinstance(data["summary"], str):
        raise ValueError(f"invalid conversation checkpoint fields: {path}")
    if count > len(records) or data["fingerprint"] != fingerprint(records[:count]):
        # Editing, deleting or replacing history invalidates derived context, including old facts.
        return 0, ""
    return count, data["summary"]


def save_checkpoint(directory: Path, records: list[dict], summary: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    atomic_write_text(str(directory / FILENAME), encode({
        "version": 1, "covered": len(records), "fingerprint": fingerprint(records), "summary": summary,
    }) + "\n")


def clear_checkpoint(directory: str | Path) -> None:
    (Path(directory) / FILENAME).unlink(missing_ok=True)
