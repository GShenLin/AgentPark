from __future__ import annotations

import uuid

from .responses_conversion import reasoning_item
from .responses_conversion import stream_item_added
from .responses_conversion import stream_item_done
from .responses_conversion import stream_reasoning_delta
from .responses_conversion import stream_reasoning_done
from .responses_conversion import stream_reasoning_part_added


class ResponsesReasoningStream:
    """Builds one Responses reasoning-summary item from a provider thinking stream."""

    def __init__(self) -> None:
        self.item_id = f"rs_{uuid.uuid4().hex}"
        self.text = ""
        self.started = False
        self.finished = False

    def feed(self, delta: str) -> list[bytes]:
        if not delta:
            return []
        if self.finished:
            raise ValueError("Provider emitted reasoning after the reasoning item completed.")
        chunks: list[bytes] = []
        if not self.started:
            chunks.append(stream_item_added(reasoning_item(self.item_id)))
            chunks.append(stream_reasoning_part_added(self.item_id))
            self.started = True
        self.text += delta
        chunks.append(stream_reasoning_delta(self.item_id, delta))
        return chunks

    def finish(self) -> list[bytes]:
        if not self.started or self.finished:
            return []
        self.finished = True
        return [
            stream_reasoning_done(self.item_id, self.text),
            stream_item_done(reasoning_item(self.item_id, self.text)),
        ]


__all__ = ["ResponsesReasoningStream"]
