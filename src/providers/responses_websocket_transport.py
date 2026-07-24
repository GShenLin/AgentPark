import copy
import json
from typing import Any
from urllib.parse import urlparse, urlunparse

from src.providers.openai_transport_errors import OpenAIHttpError, OpenAITransportError
from src.providers.provider_pressure import acquire_provider_pressure


class ResponsesWebSocketUnavailable(RuntimeError):
    pass


RESPONSES_WEBSOCKET_BETA_HEADER_VALUE = "responses_websockets=2026-02-06"


def responses_websocket_url(http_url: str) -> str:
    parsed = urlparse(str(http_url or "").strip())
    if parsed.scheme == "https":
        scheme = "wss"
    elif parsed.scheme == "http":
        scheme = "ws"
    elif parsed.scheme in {"ws", "wss"}:
        scheme = parsed.scheme
    else:
        raise ValueError(f"Unsupported Responses WebSocket URL scheme: {parsed.scheme or '<empty>'}")
    return urlunparse((scheme, parsed.netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def websocket_response_create_payload(
    *,
    request_payload: dict[str, Any],
    previous_request_payload: dict[str, Any] | None,
    previous_response: dict[str, Any] | None,
) -> tuple[dict[str, Any], bool]:
    logical_payload = copy.deepcopy(request_payload)
    ws_payload = {"type": "response.create", **copy.deepcopy(logical_payload)}
    previous_response_id = str((previous_response or {}).get("id") or "").strip()
    incremental_input = incremental_request_input(
        current_request=logical_payload,
        previous_request=previous_request_payload,
        previous_response=previous_response,
    )
    if previous_response_id and incremental_input is not None:
        ws_payload["previous_response_id"] = previous_response_id
        ws_payload["input"] = incremental_input
        return ws_payload, True
    ws_payload.pop("previous_response_id", None)
    return ws_payload, False


def incremental_request_input(
    *,
    current_request: dict[str, Any],
    previous_request: dict[str, Any] | None,
    previous_response: dict[str, Any] | None,
) -> list[Any] | None:
    if not isinstance(previous_request, dict) or not isinstance(previous_response, dict):
        return None
    if not _non_input_fields_match(previous_request, current_request):
        return None
    previous_input = previous_request.get("input")
    current_input = current_request.get("input")
    if not isinstance(previous_input, list) or not isinstance(current_input, list):
        return None
    response_output = _response_output_items(previous_response)
    normalized_response_output = _response_output_as_request_items(response_output)
    baselines = [
        [*copy.deepcopy(previous_input), *response_output],
        [*copy.deepcopy(previous_input), *normalized_response_output],
        [*copy.deepcopy(previous_input), *_without_reasoning_items(response_output)],
        [*copy.deepcopy(previous_input), *_without_reasoning_items(normalized_response_output)],
    ]
    for baseline in baselines:
        if len(current_input) >= len(baseline) and current_input[: len(baseline)] == baseline:
            return copy.deepcopy(current_input[len(baseline) :])
    return None


def parse_websocket_message(message: Any) -> str:
    if isinstance(message, bytes):
        return message.decode("utf-8", errors="replace")
    return str(message or "")


def websocket_error_message(payload: dict[str, Any]) -> tuple[int, str, str] | None:
    if str(payload.get("type") or "").strip().lower() != "error":
        return None
    status = payload.get("status_code", payload.get("status", 0))
    try:
        status_code = int(status or 0)
    except Exception:
        status_code = 0
    error = payload.get("error") if isinstance(payload.get("error"), dict) else {}
    message = str(error.get("message") or payload.get("message") or json.dumps(payload, ensure_ascii=False))
    code = str(error.get("code") or error.get("type") or "").strip()
    if code and code not in message:
        message = f"{code}: {message}"
    return status_code, code, message


class ResponsesWebSocketTransportMixin:
    def _responses_stream_data_lines(self, *, url, headers, payload_json, timeout_sec):
        if self._responses_websocket_available() and self._responses_payload_requests_stream(payload_json):
            try:
                yield from self._stream_responses_websocket_data_lines(
                    url=url,
                    headers=headers,
                    payload_json=payload_json,
                    timeout_sec=timeout_sec,
                )
                return
            except ResponsesWebSocketUnavailable as exc:
                self._emit_provider_runtime_notice(
                    message=json.dumps(
                        {
                            "fallback": "responses_http_sse",
                            "reason": str(exc),
                        },
                        ensure_ascii=False,
                    ),
                    stage="openai_responses_websocket_fallback",
                )
        yield from self._curl_post_sse_data_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout_sec,
        )

    def _responses_websocket_available(self) -> bool:
        return not bool(getattr(self, "_responses_websocket_unavailable", False))

    @staticmethod
    def _responses_payload_requests_stream(payload_json) -> bool:
        try:
            payload = json.loads(str(payload_json or ""))
        except Exception:
            return False
        return isinstance(payload, dict) and bool(payload.get("stream"))

    def _stream_responses_websocket_data_lines(self, *, url, headers, payload_json, timeout_sec):
        try:
            request_payload = json.loads(str(payload_json or ""))
        except Exception as exc:
            raise ResponsesWebSocketUnavailable(f"invalid payload JSON: {exc}") from exc
        if not isinstance(request_payload, dict):
            raise ResponsesWebSocketUnavailable("payload JSON is not an object")
        if not request_payload.get("stream"):
            raise ResponsesWebSocketUnavailable("payload is not streaming")

        previous_request = getattr(self, "_responses_ws_last_request_payload", None)
        previous_response = getattr(self, "_responses_ws_last_response", None)
        ws_payload, incremental = websocket_response_create_payload(
            request_payload=request_payload,
            previous_request_payload=previous_request,
            previous_response=previous_response,
        )
        with acquire_provider_pressure(self):
            connection = self._responses_websocket_connection(url=url, headers=headers, timeout_sec=timeout_sec)
            streamed_output_items: list[dict[str, Any]] = []
            received_response_message = False
            try:
                connection.send(json.dumps(ws_payload, ensure_ascii=False))
            except Exception as exc:
                self._close_responses_websocket()
                raise ResponsesWebSocketUnavailable(f"failed to send websocket request: {exc}") from exc

            self._emit_provider_runtime_notice(
                message=json.dumps(
                    {
                        "incremental": bool(incremental),
                        "previous_response_id_present": bool(ws_payload.get("previous_response_id")),
                        "input_item_count": len(ws_payload.get("input")) if isinstance(ws_payload.get("input"), list) else 0,
                    },
                    ensure_ascii=False,
                ),
                stage="openai_responses_websocket_request",
            )
            while True:
                try:
                    text = parse_websocket_message(connection.recv(timeout=timeout_sec))
                except TimeoutError as exc:
                    self._close_responses_websocket()
                    raise OpenAITransportError(f"websocket idle timeout after {timeout_sec}s") from exc
                except Exception as exc:
                    self._close_responses_websocket()
                    if not received_response_message and _is_websocket_keepalive_timeout(exc):
                        raise ResponsesWebSocketUnavailable(
                            f"websocket keepalive failed before first response event: {exc}"
                        ) from exc
                    raise OpenAITransportError(f"websocket receive failed: {exc}") from exc
                if not text:
                    continue
                received_response_message = True
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
                if isinstance(parsed, dict):
                    error = websocket_error_message(parsed)
                    if error is not None:
                        status_code, provider_code, message = error
                        raise OpenAIHttpError(
                            status_code,
                            message,
                            provider_code=provider_code,
                        )
                    if str(parsed.get("type") or "").strip().lower() == "response.output_item.done":
                        item = parsed.get("item")
                        if isinstance(item, dict):
                            _append_unique_response_output_item(streamed_output_items, item)
                    if str(parsed.get("type") or "").strip().lower() in {"response.completed", "response.done"}:
                        response = parsed.get("response")
                        if isinstance(response, dict):
                            self._responses_ws_last_request_payload = json.loads(json.dumps(request_payload, ensure_ascii=False))
                            self._responses_ws_last_response = _response_with_streamed_output_items(
                                response,
                                streamed_output_items,
                            )
                        yield text
                        return
                yield text

    def _responses_websocket_connection(self, *, url, headers, timeout_sec):
        connection = getattr(self, "_responses_ws_connection", None)
        if connection is not None:
            return connection
        try:
            from websockets.sync.client import connect

            connection = connect(
                responses_websocket_url(url),
                additional_headers=self._responses_websocket_headers(headers),
                open_timeout=min(10, max(1, float(timeout_sec or 60))),
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            )
        except Exception as exc:
            self._responses_websocket_unavailable = True
            raise ResponsesWebSocketUnavailable(str(exc)) from exc
        self._responses_ws_connection = connection
        return connection

    @staticmethod
    def _responses_websocket_headers(headers):
        next_headers = dict(headers or {})
        next_headers["OpenAI-Beta"] = RESPONSES_WEBSOCKET_BETA_HEADER_VALUE
        return next_headers

    def _close_responses_websocket(self) -> None:
        connection = getattr(self, "_responses_ws_connection", None)
        self._responses_ws_connection = None
        self._responses_ws_last_request_payload = None
        self._responses_ws_last_response = None
        if connection is None:
            return
        try:
            connection.close()
        except Exception:
            return


def _non_input_fields_match(previous: dict[str, Any], current: dict[str, Any]) -> bool:
    previous_cmp = {key: value for key, value in previous.items() if key not in {"input", "previous_response_id"}}
    current_cmp = {key: value for key, value in current.items() if key not in {"input", "previous_response_id"}}
    return previous_cmp == current_cmp


def _is_websocket_keepalive_timeout(error: Exception) -> bool:
    try:
        from websockets.exceptions import ConnectionClosed
    except ImportError:
        return False
    if not isinstance(error, ConnectionClosed):
        return False
    for close_frame in (getattr(error, "sent", None), getattr(error, "rcvd", None)):
        if close_frame is None:
            continue
        if int(getattr(close_frame, "code", 0) or 0) != 1011:
            continue
        if str(getattr(close_frame, "reason", "") or "").strip().casefold() == "keepalive ping timeout":
            return True
    return False


def _response_output_items(response: dict[str, Any]) -> list[Any]:
    output = response.get("output")
    return copy.deepcopy(output) if isinstance(output, list) else []


def _response_with_streamed_output_items(
    response: dict[str, Any],
    streamed_output_items: list[dict[str, Any]],
) -> dict[str, Any]:
    merged_response = copy.deepcopy(response)
    merged_output: list[Any] = []
    for item in streamed_output_items:
        _append_unique_response_output_item(merged_output, item)
    for item in _response_output_items(response):
        if isinstance(item, dict):
            _append_unique_response_output_item(merged_output, item)
        else:
            merged_output.append(item)
    if merged_output:
        merged_response["output"] = merged_output
    return merged_response


def _without_reasoning_items(items: list[Any]) -> list[Any]:
    return [
        copy.deepcopy(item)
        for item in items
        if not (isinstance(item, dict) and str(item.get("type") or "").strip().lower() == "reasoning")
    ]


def _response_output_as_request_items(items: list[Any]) -> list[Any]:
    normalized: list[Any] = []
    for item in items:
        if not isinstance(item, dict) or str(item.get("type") or "").strip().lower() != "message":
            normalized.append(copy.deepcopy(item))
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        normalized_content = []
        for part in content:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type in {"text", "input_text", "output_text"}:
                text = str(part.get("text") or "").strip()
                if text:
                    normalized_content.append({"type": "output_text", "text": text})
            elif part_type == "refusal":
                refusal = str(part.get("refusal") or part.get("text") or "").strip()
                if refusal:
                    normalized_content.append({"type": "refusal", "refusal": refusal})
        if normalized_content:
            normalized.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": normalized_content,
                    "status": "completed",
                }
            )
    return normalized


def _append_unique_response_output_item(output: list[Any], item: dict[str, Any]) -> None:
    item_id = str(item.get("id") or "").strip()
    if item_id and any(isinstance(existing, dict) and str(existing.get("id") or "").strip() == item_id for existing in output):
        return
    output.append(copy.deepcopy(item))
