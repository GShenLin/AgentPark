from __future__ import annotations

import json
import logging
import secrets
import threading
import urllib.parse
import uuid
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any, Iterator

from src.config_loader import ConfigLoader
from src.provider_auth.credentials import resolve_provider_request_credentials

from .http_transport import UpstreamHttpError
from .http_transport import open_json_request
from .http_transport import read_json_response
from .http_transport import resolve_upstream_request_policy
from .provider_adapter import create_chat_adapter
from .provider_adapter import provider_protocol
from .responses_conversion import canonical_result_to_response
from .responses_conversion import responses_request_to_canonical
from .responses_conversion import stream_failed
from .responses_passthrough import ResponsesPassthrough


MAX_REQUEST_BYTES = 32 * 1024 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GatewayLease:
    token: str
    provider_id: str
    base_url: str


class CodexProviderGateway:
    _instance: "CodexProviderGateway | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._leases: dict[str, str] = {}
        self._request_indices: dict[str, int] = {}
        self._request_observers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_type())
        self._server.daemon_threads = True
        self._server.gateway = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(target=self._server.serve_forever, name="codex-provider-gateway", daemon=True)
        self._thread.start()

    @classmethod
    def instance(cls) -> "CodexProviderGateway":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register(self, provider_id: str) -> GatewayLease:
        safe_provider_id = str(provider_id or "").strip()
        if not safe_provider_id:
            raise ValueError("provider_id is required")
        config = ConfigLoader().get_provider_config(safe_provider_id)
        modes = config.get("supportmode")
        if not isinstance(modes, list) or not any(str(mode).strip() in {"chat", "imagechat"} for mode in modes):
            raise ValueError(f"Provider {safe_provider_id!r} does not declare chat or imagechat support.")
        provider_protocol(config)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._leases[token] = safe_provider_id
            self._request_indices[token] = 0
        host, port = self._server.server_address
        return GatewayLease(
            token=token,
            provider_id=safe_provider_id,
            base_url=f"http://{host}:{port}/v1/{urllib.parse.quote(token, safe='')}",
        )

    def release(self, token: str) -> None:
        with self._lock:
            normalized_token = str(token or "")
            self._leases.pop(normalized_token, None)
            self._request_indices.pop(normalized_token, None)
            self._request_observers.pop(normalized_token, None)

    @contextmanager
    def observe_requests(
        self,
        token: str,
        observer: Callable[[dict[str, Any]], None] | None,
    ) -> Iterator[None]:
        normalized_token = str(token or "")
        if not callable(observer):
            yield
            return
        with self._lock:
            if normalized_token not in self._leases:
                raise KeyError("Unknown or expired Codex Provider gateway token.")
            if normalized_token in self._request_observers:
                raise RuntimeError("Codex Provider gateway lease already has an active request observer.")
            self._request_observers[normalized_token] = observer
        try:
            yield
        finally:
            with self._lock:
                if self._request_observers.get(normalized_token) is observer:
                    self._request_observers.pop(normalized_token, None)

    def provider_for_token(self, token: str) -> str:
        with self._lock:
            provider_id = self._leases.get(token)
        if not provider_id:
            raise KeyError("Unknown or expired Codex Provider gateway token.")
        return provider_id

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2.0)
        with self._lock:
            self._leases.clear()
            self._request_indices.clear()
            self._request_observers.clear()

    def _observe_request(
        self,
        token: str,
        *,
        provider_id: str,
        requested_model: str,
        provider_model: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            request_index = self._request_indices.get(token, 0) + 1
            self._request_indices[token] = request_index
            observer = self._request_observers.get(token)
        if not callable(observer):
            return
        event = {
            "method": "agentpark/providerGateway/request",
            "params": _request_observation(
                request_index=request_index,
                provider_id=provider_id,
                requested_model=requested_model,
                provider_model=provider_model,
                payload=payload,
            ),
        }
        try:
            observer(event)
        except Exception:
            logger.exception("Codex Provider gateway request observer failed")

    def _handler_type(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "AgentParkCodexGateway/1"

            def do_POST(self) -> None:
                self.close_connection = True
                self._response_started = False
                self._streaming = False
                self._stream_response_id = ""
                try:
                    token = self._route_token()
                    provider_id = self.server.gateway.provider_for_token(token)  # type: ignore[attr-defined]
                    payload = self._read_payload()
                    self._dispatch(token, provider_id, payload)
                except KeyError as exc:
                    self._send_error(404, str(exc))
                except UpstreamHttpError as exc:
                    if not self._response_started:
                        self._raw_error(exc.status, exc.body, exc.headers.get("content-type", "application/json"))
                    else:
                        self._send_error(exc.status, str(exc))
                except (ValueError, RuntimeError) as exc:
                    self._send_error(400, str(exc))
                except Exception as exc:
                    self._send_error(500, f"{type(exc).__name__}: {exc}")

            def _send_error(self, status: int, message: str) -> None:
                if not self._response_started:
                    self._json_error(status, message)
                    return
                if self._streaming:
                    response_id = self._stream_response_id or f"resp_agentpark_{uuid.uuid4().hex}"
                    try:
                        self.wfile.write(stream_failed(response_id, message))
                        self.wfile.flush()
                    except (BrokenPipeError, ConnectionResetError):
                        return

            def _route_token(self) -> str:
                path = urllib.parse.urlsplit(self.path).path
                parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
                if len(parts) != 3 or parts[0] != "v1" or parts[2] != "responses":
                    raise ValueError("Codex Provider gateway accepts only POST /v1/{token}/responses.")
                return parts[1]

            def _read_payload(self) -> dict[str, Any]:
                raw_length = self.headers.get("Content-Length")
                if raw_length is None:
                    raise ValueError("Content-Length is required.")
                try:
                    length = int(raw_length)
                except ValueError as exc:
                    raise ValueError("Content-Length must be an integer.") from exc
                if length < 0 or length > MAX_REQUEST_BYTES:
                    raise ValueError(f"Request body exceeds {MAX_REQUEST_BYTES} bytes.")
                raw = self.rfile.read(length)
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("Request body must be UTF-8 JSON.") from exc
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                return payload

            def _dispatch(self, token: str, provider_id: str, payload: dict[str, Any]) -> None:
                config = ConfigLoader().get_provider_config(provider_id)
                model = str(config.get("model") or "").strip()
                if not model:
                    raise ValueError(f"Provider {provider_id!r} has no model.")
                requested_model = str(payload.get("model") or "").strip()
                payload = dict(payload)
                payload["model"] = model
                self.server.gateway._observe_request(  # type: ignore[attr-defined]
                    token,
                    provider_id=provider_id,
                    requested_model=requested_model,
                    provider_model=model,
                    payload=payload,
                )
                protocol = provider_protocol(config)
                if protocol == "responses":
                    self._forward_responses(config, payload)
                    return
                canonical = responses_request_to_canonical(payload, model=model)
                adapter = create_chat_adapter(config)
                if canonical.stream:
                    response_id = f"resp_agentpark_{uuid.uuid4().hex}"
                    self._streaming = True
                    self._stream_response_id = response_id
                    self._start_stream()
                    try:
                        for chunk in adapter.stream(canonical, response_id=response_id):
                            self.wfile.write(chunk)
                            self.wfile.flush()
                    except Exception as exc:
                        self._send_error(500, str(exc))
                    return
                result = adapter.complete(canonical)
                self._json_response(200, canonical_result_to_response(result, model=model))

            def _forward_responses(self, config: dict[str, Any], payload: dict[str, Any]) -> None:
                passthrough = ResponsesPassthrough(config)
                prepared = passthrough.prepare_request(payload)
                response = self._open_responses(config, prepared.payload, force_refresh=False)
                content_type = response.headers.get("content-type", "application/json")
                if bool(prepared.payload.get("stream")):
                    self._streaming = True
                    self.send_response(response.status)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self._response_started = True
                    for line in passthrough.transform_stream(response, prepared.tools_by_wire_name):
                        self.wfile.write(line)
                        self.wfile.flush()
                    return
                value = read_json_response(response)
                value = passthrough.transform_response(value, prepared.tools_by_wire_name)
                self._json_response(200, value)

            def _open_responses(
                self,
                config: dict[str, Any],
                payload: dict[str, Any],
                *,
                force_refresh: bool,
            ):
                credentials = resolve_provider_request_credentials(config, force_refresh=force_refresh)
                base_url = credentials.base_url.rstrip("/")
                url = base_url if base_url.endswith("/responses") else f"{base_url}/responses"
                try:
                    return open_json_request(
                        url=url,
                        headers=credentials.headers,
                        payload=payload,
                        policy=resolve_upstream_request_policy(config),
                        stream=bool(payload.get("stream")),
                    )
                except UpstreamHttpError as exc:
                    if exc.status == 401 and str(config.get("authMode") or "").lower() == "codex" and not force_refresh:
                        return self._open_responses(config, payload, force_refresh=True)
                    raise

            def _start_stream(self) -> None:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.send_header("Cache-Control", "no-cache")
                self.send_header("Connection", "close")
                self.end_headers()
                self._response_started = True

            def _json_response(self, status: int, payload: dict[str, Any]) -> None:
                body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self._response_started = True
                self.wfile.write(body)

            def _json_error(self, status: int, message: str) -> None:
                self._json_response(status, {"error": {"message": str(message), "type": "agentpark_gateway_error"}})

            def _raw_error(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self._response_started = True
                self.wfile.write(body)

            def log_message(self, _format: str, *args: object) -> None:
                return

        return Handler


def _request_observation(
    *,
    request_index: int,
    provider_id: str,
    requested_model: str,
    provider_model: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    raw_input = payload.get("input")
    input_item_count = len(raw_input) if isinstance(raw_input, list) else int(bool(raw_input))
    tools = payload.get("tools")
    tools_included_count = len(tools) if isinstance(tools, list) else 0
    if isinstance(raw_input, list):
        tools_included_count += sum(
            len(item.get("tools"))
            for item in raw_input
            if isinstance(item, dict)
            and item.get("type") == "additional_tools"
            and isinstance(item.get("tools"), list)
        )
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    return {
        "request_index": request_index,
        "provider_id": provider_id,
        "requested_model": requested_model,
        "provider_model": provider_model,
        "payload_chars": len(encoded),
        "approx_payload_tokens": (len(encoded) + 3) // 4,
        "input_item_count": input_item_count,
        "tools_included_count": tools_included_count,
        "instructions_chars": len(str(payload.get("instructions") or "")),
        "stream": payload.get("stream") is True,
    }


__all__ = ["CodexProviderGateway", "GatewayLease"]
