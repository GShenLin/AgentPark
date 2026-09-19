from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

from .checkpoint import encode, estimate_tokens, load_checkpoint
from .model import PROMPT
from .settings import ConversationSettings

CHECKPOINT_PREFIX = "[Conversation continuation checkpoint — historical context]\n"


def checkpoint_message(summary: str) -> list[dict]:
    return [{"role": "assistant", "content": CHECKPOINT_PREFIX + summary}] if summary else []


class ConversationWindow:
    def __init__(self, directory: Path, settings: ConversationSettings, complete: Callable[[str], str]):
        self.directory, self.settings, self.complete = directory, settings, complete

    def prepare(self, records: list[dict], messages: list[dict], *, reserved_tokens: int,
                publish: Callable[[list[dict], str], None]) -> list[dict]:
        if len(records) != len(messages):
            raise ValueError("conversation records and projected messages must have the same length")
        cfg = self.settings
        available = cfg.input_tokens - reserved_tokens
        if available <= cfg.summary_tokens + 128:
            raise ValueError("current input, instructions and tools leave insufficient conversation budget; "
                             "increase conversationContext.input_tokens or reduce the current input/tools")
        covered, summary = load_checkpoint(self.directory, records)
        remaining = messages[covered:]
        if estimate_tokens(checkpoint_message(summary) + remaining) <= available:
            return checkpoint_message(summary) + remaining
        retain_budget = min(cfg.retain_tokens, available - cfg.summary_tokens - 128)
        boundary = len(messages)
        for index in range(len(messages) - 1, covered - 1, -1):
            if estimate_tokens(messages[index:]) > retain_budget:
                break
            if messages[index]["role"] == "user":
                boundary = index
        if boundary <= covered:
            raise ValueError("conversation compaction cannot select an older prefix within the budget")
        # Batch the selected prefix; only oversized inputs require multiple model calls.
        text = "\n".join(encode({"source_id": records[index]["id"], "message": messages[index]})
                         for index in range(covered, boundary))
        summary = self._fold(summary, text)
        result = checkpoint_message(summary) + messages[boundary:]
        if estimate_tokens(result) > available:
            raise ValueError("compacted conversation still exceeds its input budget")
        publish(records[:boundary], summary)
        return result

    def _fold(self, summary: str, text: str) -> str:
        cfg = self.settings
        max_input = cfg.input_tokens - cfg.summary_tokens - estimate_tokens(PROMPT) - 256
        part = 0
        while text:
            part += 1
            base = {"previous_summary": summary, "summary_token_budget": cfg.summary_tokens,
                    "segment": part, "history": ""}
            capacity = (max_input - estimate_tokens(base)) * 4
            if capacity <= 0:
                raise ValueError("conversation summary leaves no compaction input budget")
            chunk = text.encode("utf-8")[:capacity].decode("utf-8", errors="ignore")
            payload = {**base, "history": chunk}
            while estimate_tokens(payload) > max_input and chunk:
                excess = estimate_tokens(payload) - max_input
                chunk = chunk[:max(0, len(chunk) - max(1, excess * 4))]
                payload["history"] = chunk
            if not chunk:
                raise ValueError("cannot fit a conversation segment in the compaction budget")
            output = json.loads(self.complete(encode(payload)))
            if not isinstance(output, dict) or set(output) != {"summary"}:
                raise ValueError("conversation compaction requires exactly the summary field")
            candidate = output["summary"]
            if not isinstance(candidate, str) or not candidate.strip():
                raise ValueError("conversation compaction summary must be non-empty text")
            if estimate_tokens(candidate) > cfg.summary_tokens:
                raise ValueError("conversation compaction summary exceeds configured budget")
            summary = candidate.strip()
            text = text[len(chunk):]
        return summary
