from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from src.providers.responses_payload_log import write_responses_payload_log
from src.providers.provider_request_summary import build_provider_request_summary


@dataclass(frozen=True)
class ResponsesRequestPayload:
    payload_json: str
    request_summary: dict[str, Any]
    input_item_count: int


def build_and_emit_responses_request_payload(
    runtime,
    *,
    request_index: int,
    request_input: list[Any],
    tools_payload: list[Any],
    use_stream: bool,
    mode_decision,
    context_update: dict[str, Any],
    request_instructions: str,
    provider_options: dict[str, Any],
) -> ResponsesRequestPayload:
    payload = runtime._build_responses_payload(
        current_input=request_input,
        tools_payload=tools_payload,
        use_stream=use_stream,
        provider_options=provider_options,
        instructions=request_instructions,
    )
    request_summary = build_provider_request_summary(
        request_index=request_index,
        current_input=request_input,
        tools_payload=tools_payload,
        stream=use_stream,
        request_api="responses",
        responses_mode=mode_decision.mode,
        requested_responses_mode=mode_decision.requested_mode,
        context_update=context_update,
        instructions=request_instructions,
        tool_choice=str(payload.get("tool_choice") or ""),
        parallel_tool_calls=payload.get("parallel_tool_calls"),
        include=payload.get("include"),
    )
    payload_json = json.dumps(payload, ensure_ascii=False)
    payload_log = write_responses_payload_log(
        runtime,
        request_index=request_index,
        payload=payload,
        request_summary=request_summary,
        payload_json=payload_json,
    )
    if payload_log:
        if payload_log.get("path"):
            request_summary["payload_log_path"] = str(payload_log.get("path") or "")
        if payload_log.get("error"):
            request_summary["payload_log_error"] = str(payload_log.get("error") or "")
        runtime._emit_responses_payload_log(payload_log)
    runtime._emit_provider_request_summary(request_summary)
    runtime._emit_responses_request_start(
        request_index=request_index,
        input_item_count=len(request_input) if isinstance(request_input, list) else 0,
        stream=use_stream,
        responses_mode=mode_decision.mode,
        requested_responses_mode=mode_decision.requested_mode,
    )
    return ResponsesRequestPayload(
        payload_json=payload_json,
        request_summary=request_summary,
        input_item_count=len(request_input) if isinstance(request_input, list) else 0,
    )
