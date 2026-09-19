from __future__ import annotations

"""Responses SSE adaptation for Seed text calls.

Assistant message events are held until output_item.done so a split marker can
never leak to the client. Converted calls are released only on a successful
response.completed, with the same call ids in both item and response events.
Reasoning and native tool events retain their existing streaming behavior.
"""

import copy
import json
from collections.abc import Iterable
from typing import Any

from .contracts import CodexProtocolError
from .doubao_seed_response import SeedResponseNormalizer
from .doubao_seed_tools import SeedToolRegistry


def normalize_seed_stream(chunks: Iterable[bytes], tools: SeedToolRegistry) -> Iterable[bytes]:
    state = _SeedStream(tools)
    sequence = 0
    try:
        for chunk in chunks:
            data = b"\n".join(
                line[5:].lstrip() for line in chunk.splitlines() if line.startswith(b"data:")
            )
            if not data or data == b"[DONE]":
                if data == b"[DONE]":
                    state.finish()
                yield chunk
                continue
            event = json.loads(data.decode("utf-8"))
            if not isinstance(event, dict):
                raise CodexProtocolError("Seed Responses SSE event must be an object.")
            for updated in state.accept(event):
                updated["sequence_number"] = sequence
                sequence += 1
                yield _encode(updated)
        state.finish()
    finally:
        close = getattr(chunks, "close", None)
        if callable(close):
            close()


class _SeedStream:
    def __init__(self, tools: SeedToolRegistry) -> None:
        self.normalizer = SeedResponseNormalizer(tools)
        self.buffers: dict[int, list[dict[str, Any]]] = {}
        self.done: dict[int, dict[str, Any]] = {}
        self.generated: list[dict[str, Any]] = []
        self.max_index = -1
        self.terminal = False

    def accept(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        if self.terminal:
            raise CodexProtocolError("Seed stream emitted an event after its terminal event.")
        kind = event.get("type")
        index = event.get("output_index")
        if isinstance(index, int):
            self.max_index = max(self.max_index, index)
        item = event.get("item")
        if kind == "response.output_item.added" and isinstance(item, dict) and item.get("type") == "message":
            index = _index(event)
            if index in self.buffers or index in self.done:
                raise CodexProtocolError("Seed stream reused an output index.")
            self.buffers[index] = [event]
            return []
        if kind == "response.output_item.done" and isinstance(item, dict):
            if isinstance(index, int):
                if index in self.done:
                    raise CodexProtocolError("Seed stream repeated output_item.done.")
                self.done[index] = item
            if item.get("type") == "message":
                updated, calls = self.normalizer.message(item)
                buffered = self.buffers.pop(index, [])
                if calls:
                    self.generated.extend(calls)
                    return _message_events(updated, _index(event))
                return [*buffered, event]
        if isinstance(index, int) and index in self.buffers:
            self.buffers[index].append(event)
            return []
        if kind == "response.completed":
            return self._completed(event)
        if kind in {"response.failed", "response.incomplete", "error"}:
            self.terminal = True
            self.buffers.clear()
            self.generated.clear()
        return [event]

    def _completed(self, event: dict[str, Any]) -> list[dict[str, Any]]:
        response = event.get("response")
        if not isinstance(response, dict):
            raise CodexProtocolError("Seed completed event requires a response object.")
        response = copy.deepcopy(response)
        output = response.get("output")
        if output is None:
            if self.buffers:
                raise CodexProtocolError("Seed stream completed with unfinished messages.")
            output = [item for _, item in sorted(self.done.items())]
            response["output"] = output
        if not isinstance(output, list):
            raise CodexProtocolError("Seed completed response output must be an array.")
        result: list[dict[str, Any]] = []
        for index, item in enumerate(output):
            if index in self.done:
                # Only textual calls require identical snapshots; leave native
                # item metadata and other provider normalization untouched.
                self.normalizer.message(item)
                continue
            updated, calls = self.normalizer.message(item)
            if index in self.buffers:
                self.buffers.pop(index)
                result.extend(_message_events(updated, index))
            elif calls:
                result.extend(_message_events(updated, index))
            self.generated.extend(calls)
        if self.buffers:
            raise CodexProtocolError("Seed stream completed without its buffered messages.")
        normalized = self.normalizer.response(response)
        self.max_index = max(self.max_index, len(output) - 1)
        expected = normalized["output"][len(output):]
        if [call["call_id"] for call in self.generated] != [call["call_id"] for call in expected]:
            raise CodexProtocolError("Seed tool calls differ between completed snapshots.")
        for offset, call in enumerate(self.generated, self.max_index + 1):
            result.extend(_call_events(call, offset))
        self.terminal = True
        result.append({**event, "response": normalized})
        return result

    def finish(self) -> None:
        if not self.terminal:
            raise CodexProtocolError("Seed Responses stream ended without a terminal event.")


def _message_events(item: dict[str, Any], index: int) -> list[dict[str, Any]]:
    added = {**item, "status": "in_progress", "content": []}
    events = [{"type": "response.output_item.added", "output_index": index, "item": added}]
    for content_index, part in enumerate(item.get("content", [])):
        base = {"item_id": item["id"], "output_index": index, "content_index": content_index}
        empty = {**part, "text": ""} if part.get("type") in {"output_text", "text"} else part
        events.append({"type": "response.content_part.added", **base, "part": empty})
        if part.get("type") in {"output_text", "text"}:
            if part["text"]:
                events.append({"type": "response.output_text.delta", **base, "delta": part["text"]})
            events.append({"type": "response.output_text.done", **base, "text": part["text"]})
        events.append({"type": "response.content_part.done", **base, "part": part})
    events.append({"type": "response.output_item.done", "output_index": index, "item": item})
    return events


def _call_events(item: dict[str, Any], index: int) -> list[dict[str, Any]]:
    custom = item["type"] == "custom_tool_call"
    field = "input" if custom else "arguments"
    prefix = "response.custom_tool_call_input" if custom else "response.function_call_arguments"
    base = {"item_id": item["id"], "output_index": index}
    return [
        {"type": "response.output_item.added", "output_index": index,
         "item": {**item, "status": "in_progress", field: ""}},
        {"type": f"{prefix}.delta", **base, "delta": item[field]},
        {"type": f"{prefix}.done", **base, field: item[field]},
        {"type": "response.output_item.done", "output_index": index,
         "item": {**item, "status": "completed"}},
    ]


def _index(event: dict[str, Any]) -> int:
    index = event.get("output_index")
    if not isinstance(index, int) or isinstance(index, bool) or index < 0:
        raise CodexProtocolError("Seed message event requires a nonnegative output_index.")
    return index


def _encode(event: dict[str, Any]) -> bytes:
    return (f"event: {event['type']}\ndata: " + json.dumps(event, ensure_ascii=False) + "\n\n").encode("utf-8")
