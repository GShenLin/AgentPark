from __future__ import annotations

from typing import Any

from src.providers.mid_turn_user_inputs import consume_mid_turn_user_messages


class ResponsesStructuredResultAccumulator:
    def __init__(self) -> None:
        self._value: dict[str, Any] = {}

    def add(self, value: object) -> dict[str, Any]:
        if isinstance(value, dict):
            for key, identity_key in (
                ("server_tool_calls", "call_id"),
                ("citations", "url"),
            ):
                incoming = value.get(key)
                if isinstance(incoming, list):
                    self._merge_items(key, identity_key, incoming)
            response_metadata = value.get("response_metadata")
            if isinstance(response_metadata, dict) and response_metadata:
                self._value["response_metadata"] = dict(response_metadata)
        return {
            key: (list(items) if isinstance(items, list) else dict(items))
            for key, items in self._value.items()
            if items
        }

    def _merge_items(
        self,
        key: str,
        identity_key: str,
        incoming: list[Any],
    ) -> None:
        merged = self._value.setdefault(key, [])
        positions = {
            str(item.get(identity_key) or "").strip(): index
            for index, item in enumerate(merged)
            if isinstance(item, dict) and str(item.get(identity_key) or "").strip()
        }
        for item in incoming:
            if not isinstance(item, dict):
                continue
            identity = str(item.get(identity_key) or "").strip()
            if identity and identity in positions:
                merged[positions[identity]] = dict(item)
            else:
                if identity:
                    positions[identity] = len(merged)
                merged.append(dict(item))


class ResponsesStreamCallbacks:
    def __init__(
        self,
        *,
        runtime: object,
        stream_handler: object,
        thinking_stream_handler: object,
        stream_text: object,
        thinking_text: object,
    ) -> None:
        self._runtime = runtime
        self._stream_handler = stream_handler
        self._thinking_stream_handler = thinking_stream_handler
        self._stream_text = stream_text
        self._thinking_text = thinking_text

    def on_stream(self, delta_text: str, full_text: str) -> None:
        self._runtime._emit_stream_text(
            self._stream_handler,
            delta_text,
            self._stream_text.update(delta_text, full_text),
        )

    def on_thinking(
        self,
        delta_text: str,
        full_text: str,
        provider: str = "",
    ) -> None:
        if not callable(self._thinking_stream_handler):
            return
        resolved_full = self._thinking_text.update(delta_text, full_text)
        self._thinking_stream_handler(delta_text, resolved_full, provider)


def consume_responses_mid_turn_input_items(runtime: object) -> list[dict[str, Any]]:
    messages = consume_mid_turn_user_messages(runtime)
    items = runtime._build_responses_input(messages)
    if items:
        runtime._emit_responses_notice(
            stage="openai_responses_mid_turn_user_input",
            payload={
                "message_count": len(messages),
                "input_item_count": len(items),
            },
        )
    return items


def emit_responses_turn_debug(
    runtime: object,
    mode_decision: object,
    **kwargs: Any,
) -> None:
    runtime._emit_responses_turn_debug(
        **kwargs,
        responses_mode=mode_decision.mode,
        requested_responses_mode=mode_decision.requested_mode,
        responses_mode_fallback_reason=mode_decision.fallback_reason,
    )


def checkpoint_completed_tool_context(
    runtime: object,
    checkpoint: object,
    *,
    items: object,
    function_calls: object,
    executions: object,
) -> list[Any] | None:
    from src.providers.responses_completed_tool_checkpoint import load_task_direction_snapshot

    result = checkpoint.maybe_checkpoint(
        items=items,
        function_calls=function_calls,
        executions=executions,
        task_direction_loader=lambda: load_task_direction_snapshot(runtime),
    )
    if result is None:
        return None
    runtime._emit_responses_notice(
        stage="openai_responses_completed_tool_checkpoint",
        payload=result.to_notice_payload(),
    )
    return list(result.items)


def close_responses_item_tool_runner(runner: object) -> None:
    if runner is not None:
        runner.close()


def abort_responses_item_tool_runner(
    runner: object,
    reason: str,
    error: Exception,
) -> None:
    if runner is not None:
        runner.abort(reason=reason, error=f"{type(error).__name__}: {error}")


def finish_responses_message(
    runtime: object,
    *,
    content: object,
    stream_text: str,
    structured_result: dict[str, Any],
    raw_result: object,
) -> object:
    resolved_content = str(content or "")
    if resolved_content:
        runtime.Message("assistant", resolved_content, **structured_result)
        return _public_responses_result(resolved_content, structured_result)
    if stream_text:
        runtime.Message("assistant", stream_text, **structured_result)
        return _public_responses_result(stream_text, structured_result)
    runtime.Message("assistant", content)
    import json

    return json.dumps(raw_result, ensure_ascii=False)


def _public_responses_result(
    content: str,
    structured_result: dict[str, Any],
) -> object:
    public_result = {
        key: value
        for key, value in structured_result.items()
        if key in {"server_tool_calls", "citations"} and value
    }
    return {"response": content, **public_result} if public_result else content


__all__ = [
    "ResponsesStreamCallbacks",
    "ResponsesStructuredResultAccumulator",
    "abort_responses_item_tool_runner",
    "checkpoint_completed_tool_context",
    "close_responses_item_tool_runner",
    "consume_responses_mid_turn_input_items",
    "emit_responses_turn_debug",
    "finish_responses_message",
]
