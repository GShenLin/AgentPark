"""Durable conversation commit metadata, stored with the node it describes.

Call only after a successful history write, under the node memory transaction.
Keeping identity out of this file makes rename/move/delete follow node storage.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, StrictInt

from src.file_transaction import atomic_write_text
from .node_memory_errors import NodeMemoryPersistenceError, NodeMemoryPersistenceFailure


FILENAME = ".conversation-activity.json"


class ConversationActivity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    saved_at_ns: StrictInt = Field(gt=0)


def record_conversation_commit(node_dir: str) -> None:
    activity = ConversationActivity(saved_at_ns=time.time_ns())
    path = str(Path(node_dir) / FILENAME)
    try:
        atomic_write_text(path, activity.model_dump_json() + "\n")
    except OSError as exc:
        raise NodeMemoryPersistenceError([
            NodeMemoryPersistenceFailure("conversation_activity", path, str(exc)),
        ]) from exc


def read_conversation_commit(node_dir: Path) -> int | None:
    try:
        payload = (node_dir / FILENAME).read_text(encoding="utf-8")
    except FileNotFoundError:
        return None  # No conversation has been committed since tracking was enabled.
    return ConversationActivity.model_validate(json.loads(payload)).saved_at_ns
