from __future__ import annotations

import io
import json

from src.codex_runtime.anthropic_adapter import AnthropicMessagesAdapter
from src.codex_runtime.contracts import CanonicalMessage
from src.codex_runtime.contracts import CanonicalRequest
from src.codex_runtime.contracts import CanonicalTool
from src.codex_runtime.gemini_adapter import GeminiGenerateContentAdapter
from src.codex_runtime.http_transport import UpstreamResponse
from src.codex_runtime.openai_chat_adapter import OpenAIChatAdapter


def _request() -> CanonicalRequest:
    return CanonicalRequest(
        model="model",
        messages=(CanonicalMessage(role="user", content="hello"),),
        tools=(
            CanonicalTool(
                name="lookup",
                description="Lookup",
                input_schema={"type": "object", "properties": {"query": {"type": "string"}}},
            ),
        ),
        stream=True,
    )


def _response(events: list[dict]) -> UpstreamResponse:
    body = "".join(f"data: {json.dumps(event)}\n\n" for event in events).encode("utf-8")
    return UpstreamResponse(status=200, headers={"content-type": "text/event-stream"}, body=io.BytesIO(body))


def _payloads(chunks) -> list[dict]:
    output = []
    for chunk in chunks:
        data_line = next(line for line in chunk.decode("utf-8").splitlines() if line.startswith("data:"))
        output.append(json.loads(data_line[5:].strip()))
    return output


def test_anthropic_stream_reassembles_incremental_tool_json(monkeypatch):
    events = [
        {"type": "message_start", "message": {"id": "msg", "usage": {"input_tokens": 3}}},
        {"type": "content_block_start", "index": 2, "content_block": {"type": "thinking", "thinking": ""}},
        {"type": "content_block_delta", "index": 2, "delta": {"type": "thinking_delta", "thinking": "Reason"}},
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
        {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hi"}},
        {
            "type": "content_block_start",
            "index": 1,
            "content_block": {"type": "tool_use", "id": "tool-1", "name": "lookup", "input": {}},
        },
        {
            "type": "content_block_delta",
            "index": 1,
            "delta": {"type": "input_json_delta", "partial_json": '{"query":"Codex"}'},
        },
        {"type": "message_delta", "usage": {"output_tokens": 4}},
    ]
    monkeypatch.setattr("src.codex_runtime.anthropic_adapter.open_json_request", lambda **_kwargs: _response(events))
    adapter = AnthropicMessagesAdapter(
        {"type": "claude", "baseUrl": "http://example.test/v1", "apiKey": "key"}
    )

    payloads = _payloads(adapter.stream(_request(), response_id="resp-fixed"))
    tool_item = next(payload["item"] for payload in payloads if payload["type"] == "response.output_item.done" and payload["item"]["type"] == "function_call")

    assert payloads[0]["response"]["id"] == "resp-fixed"
    assert any(payload.get("type") == "response.reasoning_summary_text.delta" for payload in payloads)
    assert tool_item["arguments"] == '{"query":"Codex"}'
    assert payloads[-1]["response"]["usage"]["total_tokens"] == 7


def test_openai_compatible_stream_converts_reasoning_content(monkeypatch):
    events = [
        {"choices": [{"index": 0, "delta": {"reasoning_content": "Reason"}}]},
        {"choices": [{"index": 0, "delta": {"content": "Answer"}}]},
    ]
    monkeypatch.setattr("src.codex_runtime.openai_chat_adapter.open_json_request", lambda **_kwargs: _response(events))
    adapter = OpenAIChatAdapter(
        {"type": "zhipu", "baseUrl": "http://example.test/v1", "apiKey": "key"}
    )

    payloads = _payloads(adapter.stream(_request(), response_id="resp-fixed"))

    assert any(payload.get("type") == "response.reasoning_summary_text.delta" for payload in payloads)
    assert any(payload.get("delta") == "Answer" for payload in payloads)


def test_gemini_stream_converts_text_and_function_call(monkeypatch):
    events = [
        {"candidates": [{"content": {"parts": [{"text": "Reason", "thought": True}, {"text": "Hi"}]}}]},
        {
            "candidates": [
                {"content": {"parts": [{"functionCall": {"name": "lookup", "args": {"query": "Codex"}}}]}}
            ],
            "usageMetadata": {"promptTokenCount": 2, "candidatesTokenCount": 3},
        },
    ]
    monkeypatch.setattr("src.codex_runtime.gemini_adapter.open_json_request", lambda **_kwargs: _response(events))
    adapter = GeminiGenerateContentAdapter(
        {"type": "gemini", "baseUrl": "http://example.test/v1beta", "apiKey": "key"}
    )

    payloads = _payloads(adapter.stream(_request(), response_id="resp-fixed"))
    tool_item = next(payload["item"] for payload in payloads if payload["type"] == "response.output_item.done" and payload["item"]["type"] == "function_call")

    assert any(payload.get("delta") == "Hi" for payload in payloads)
    assert any(payload.get("type") == "response.reasoning_summary_text.delta" for payload in payloads)
    assert json.loads(tool_item["arguments"]) == {"query": "Codex"}
    assert payloads[-1]["response"]["usage"]["total_tokens"] == 5
