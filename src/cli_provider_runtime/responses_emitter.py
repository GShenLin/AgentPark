"""Stateful Responses events with stable item identities and complete lifecycles."""
from __future__ import annotations

import uuid
from .responses_wire import _sse, _usage, message_item, reasoning_item, tool_call_item


class ResponsesEmitter:
    def __init__(self, response_id: str, model: str):
        self.response_id, self.model = response_id, model
        self.output: list[dict] = []
        self.sequence = 0
        self.message_index: int | None = None
        self.reasoning_index: int | None = None
        self.reasoning_finished = False

    def event(self, kind: str, **fields) -> bytes:
        result = _sse(kind, {"type": kind, "sequence_number": self.sequence, **fields})
        self.sequence += 1
        return result

    def created(self) -> bytes:
        return self.event("response.created", response={"id": self.response_id,
            "object": "response", "status": "in_progress", "model": self.model, "output": []})

    def added(self, item: dict) -> bytes:
        self.output.append(item)
        return self.event("response.output_item.added", output_index=len(self.output) - 1, item=item)

    def text(self, delta: str):
        if not delta:
            return
        yield from self.finish_reasoning()
        if self.message_index is None:
            self.message_index = len(self.output)
            item = message_item(f"msg_{uuid.uuid4().hex}")
            yield self.added(item)
            yield self.event("response.content_part.added", item_id=item["id"],
                output_index=self.message_index, content_index=0, part=item["content"][0])
        item = self.output[self.message_index]
        item["content"][0]["text"] += delta
        yield self.event("response.output_text.delta", item_id=item["id"],
            output_index=self.message_index, content_index=0, delta=delta)

    def reasoning(self, delta: str):
        if not delta:
            return
        if self.reasoning_finished:
            raise ValueError("Provider emitted reasoning after its item completed.")
        if self.reasoning_index is None:
            self.reasoning_index = len(self.output)
            item = reasoning_item(f"rs_{uuid.uuid4().hex}")
            yield self.added(item)
            item["summary"] = [{"type": "summary_text", "text": ""}]
            yield self.event("response.reasoning_summary_part.added", item_id=item["id"],
                output_index=self.reasoning_index, summary_index=0, part=item["summary"][0])
        item = self.output[self.reasoning_index]
        item["summary"][0]["text"] += delta
        yield self.event("response.reasoning_summary_text.delta", item_id=item["id"],
            output_index=self.reasoning_index, summary_index=0, delta=delta)

    def finish_reasoning(self):
        if self.reasoning_index is None or self.reasoning_finished:
            return
        self.reasoning_finished = True
        item = self.output[self.reasoning_index]
        base = {"item_id": item["id"], "output_index": self.reasoning_index, "summary_index": 0}
        yield self.event("response.reasoning_summary_text.done", **base, text=item["summary"][0]["text"])
        yield self.event("response.reasoning_summary_part.done", **base, part=item["summary"][0])
        yield self.event("response.output_item.done", output_index=self.reasoning_index, item=item)

    def completed(self, result):
        yield from self.finish_reasoning()
        if self.message_index is not None:
            item = self.output[self.message_index]
            item["status"] = "completed"
            base = {"item_id": item["id"], "output_index": self.message_index, "content_index": 0}
            yield self.event("response.output_text.done", **base, text=item["content"][0]["text"])
            yield self.event("response.content_part.done", **base, part=item["content"][0])
            yield self.event("response.output_item.done", output_index=self.message_index, item=item)
        for call in result.tool_calls:
            item = tool_call_item(call)
            key = "input" if call.kind == "custom" else "arguments"
            initial = {**item, "status": "in_progress"}
            if call.kind != "tool_search":
                initial[key] = ""
            yield self.added(initial)
            index = len(self.output) - 1
            kind = "custom_tool_call_input" if call.kind == "custom" else "function_call_arguments"
            if call.kind != "tool_search":
                yield self.event(f"response.{kind}.delta", item_id=item["id"], output_index=index, delta=item[key])
                yield self.event(f"response.{kind}.done", item_id=item["id"], output_index=index, **{key: item[key]})
            self.output[index] = item
            yield self.event("response.output_item.done", output_index=index, item=item)
        yield self.event("response.completed", response={"id": self.response_id, "object": "response",
            "status": "completed", "model": self.model, "output": self.output, "usage": _usage(result)})
