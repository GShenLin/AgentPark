"""Durable authorization and idempotency for uploading completed call transcripts.

Task execution still requires a live lease. Transcript retries only require this
receipt and current node access, so a server restart cannot orphan a new call.
"""
import hashlib
from pathlib import Path
from typing import Literal

from fastapi import HTTPException
from pydantic import BaseModel, ConfigDict

from src.file_transaction import atomic_write_text
from .node_memory_store import append_node_memory_entry_once
from .node_memory_transaction import run_memory_transaction
from .node_voice_records import VoiceFinish, build_voice_record
from .shared import now_text


class VoiceReceipt(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    node_id: str
    graph_id: str
    owner: str
    started_at: str
    state: Literal["open", "pending", "saved", "abandoned"] = "open"
    ended_at: str = ""
    payload_hash: str = ""
    node_owned_dialogue: bool = False


class VoiceReceiptStore:
    def __init__(self, runtime):
        self.runtime = runtime

    def _path(self, node_id, graph_id, session_id):
        directory = Path(self.runtime._node_messages_path(node_id, graph_id)).parent
        filename = hashlib.sha256(session_id.encode("utf-8")).hexdigest() + ".json"
        return directory / ".voice-calls" / filename

    def register(self, node_id, graph_id, session_id, owner, started_at, *, node_owned_dialogue=False):
        receipt = VoiceReceipt(node_id=node_id, graph_id=graph_id, owner=owner, started_at=started_at,
                               node_owned_dialogue=node_owned_dialogue)
        self._write(self._path(node_id, graph_id, session_id), receipt)

    @staticmethod
    def _write(path, receipt):
        atomic_write_text(str(path), receipt.model_dump_json() + "\n")

    def _read(self, node_id, graph_id, session_id, owner):
        path = self._path(node_id, graph_id, session_id)
        try:
            receipt = VoiceReceipt.model_validate_json(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise HTTPException(404, "找不到本次通话的保存凭据；升级前开始的通话无法在服务重启后补存。") from None
        if (receipt.node_id, receipt.graph_id, receipt.owner) != (node_id, graph_id, owner):
            raise HTTPException(404, "语音会话不存在。")
        return path, receipt

    def abandon(self, node_id, graph_id, session_id, owner):
        path, receipt = self._read(node_id, graph_id, session_id, owner)
        if receipt.state != "open":
            raise HTTPException(409, "语音记录已经开始保存。")
        receipt.state = "abandoned"
        self._write(path, receipt)

    def finish(self, node_id, graph_id, session_id, owner, payload: VoiceFinish):
        memory = self.runtime._node_memory_path(node_id, graph_id)
        messages = self.runtime._node_messages_path(node_id, graph_id)

        def save():
            path, receipt = self._read(node_id, graph_id, session_id, owner)
            if receipt.state == "abandoned":
                raise HTTPException(409, "本次通话已取消。")
            digest = hashlib.sha256(payload.model_dump_json().encode("utf-8")).hexdigest()
            if receipt.payload_hash and digest != receipt.payload_hash:
                raise HTTPException(409, "语音记录不能重复提交不同内容。")
            if receipt.state == "open":
                receipt.state = "pending"
                receipt.payload_hash = digest
                receipt.ended_at = now_text()
                self._write(path, receipt)
            record = build_voice_record(session_id, receipt.started_at, payload, ended_at=receipt.ended_at,
                                        history_owner="node" if receipt.node_owned_dialogue else "voice")
            if receipt.state != "saved":
                append_node_memory_entry_once(memory, messages, "voice", record)
                receipt.state = "saved"
                self._write(path, receipt)
            return record["id"]

        return run_memory_transaction(memory, messages, save)
