from __future__ import annotations

# Claude session configuration contract.
import hashlib
import json
import os
from dataclasses import dataclass


@dataclass(frozen=True)
class ClaudeSessionSpec:
    session_key: str
    provider_id: str
    model: str
    command: str
    cwd: str
    permission_mode: str
    state_path: str
    instruction: str = ""
    reasoning_effort: str = ""

    def signature(self) -> str:
        payload = {
            "version": 1,
            "provider_id": self.provider_id,
            "model": self.model,
            "command": self.command,
            "cwd": os.path.normcase(os.path.abspath(self.cwd)),
            "permission_mode": self.permission_mode,
            "instruction": self.instruction,
            "reasoning_effort": self.reasoning_effort,
        }
        encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


__all__ = ["ClaudeSessionSpec"]
