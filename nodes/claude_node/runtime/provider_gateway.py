from __future__ import annotations

import json
import logging
import secrets
import threading
import urllib.parse
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from typing import Any, Iterator

from src.cli_provider_runtime.http_transport import UpstreamHttpError
from src.cli_provider_runtime.gateway_dispatch import dispatch_messages
from src.cli_provider_runtime.provider_adapter import provider_protocol
from src.config_loader import ConfigLoader
from src.provider_models import resolve_provider_model


MAX_REQUEST_BYTES = 32 * 1024 * 1024
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ClaudeGatewayLease:
    token: str
    provider_id: str
    base_url: str


class ClaudeProviderGateway:
    _instance: "ClaudeProviderGateway | None" = None
    _instance_lock = threading.Lock()

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._models: dict[str, str] = {}
        self._leases: dict[str, str] = {}
        self._reasoning_efforts: dict[str, str] = {}
        self._request_indices: dict[str, int] = {}
        self._request_observers: dict[str, Callable[[dict[str, Any]], None]] = {}
        self._server = ThreadingHTTPServer(("127.0.0.1", 0), self._handler_type())
        self._server.daemon_threads = True
        self._server.gateway = self  # type: ignore[attr-defined]
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="claude-provider-gateway",
            daemon=True,
        )
        self._thread.start()

    @classmethod
    def instance(cls) -> "ClaudeProviderGateway":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    def register(
        self,
        provider_id: str,
        *,
        reasoning_effort: str = "",
        model: str = "",
    ) -> ClaudeGatewayLease:
        safe_provider_id = str(provider_id or "").strip()
        if not safe_provider_id:
            raise ValueError("provider_id is required")
        config = ConfigLoader().get_provider_config(safe_provider_id)
        modes = config.get("supportmode")
        if not isinstance(modes, list) or not any(
            str(mode).strip() in {"chat", "imagechat"} for mode in modes
        ):
            raise ValueError(f"Provider {safe_provider_id!r} does not declare chat or imagechat support.")
        provider_protocol(config)
        normalized_effort = str(reasoning_effort or "").strip()
        if normalized_effort not in {"", "low", "medium", "high", "xhigh", "max"}:
            raise ValueError(f"Unsupported Claude reasoning effort: {normalized_effort!r}.")
        selected_model = resolve_provider_model(config, model)
        token = secrets.token_urlsafe(32)
        with self._lock:
            self._models[token] = selected_model
            self._leases[token] = safe_provider_id
            self._reasoning_efforts[token] = normalized_effort
            self._request_indices[token] = 0
        host, port = self._server.server_address
        return ClaudeGatewayLease(
            token=token,
            provider_id=safe_provider_id,
            base_url=f"http://{host}:{port}/{urllib.parse.quote(token, safe='')}",
        )

    def release(self, token: str) -> None:
        with self._lock:
            value = str(token or "")
            self._leases.pop(value, None)
            self._models.pop(value, None)
            self._reasoning_efforts.pop(value, None)
            self._request_indices.pop(value, None)
            self._request_observers.pop(value, None)

    @contextmanager
    def observe_requests(
        self,
        token: str,
        observer: Callable[[dict[str, Any]], None] | None,
    ) -> Iterator[None]:
        normalized = str(token or "")
        if not callable(observer):
            yield
            return
        with self._lock:
            if normalized not in self._leases:
                raise KeyError("Unknown or expired Claude Provider gateway token.")
            if normalized in self._request_observers:
                raise RuntimeError("Claude Provider gateway lease already has an active request observer.")
            self._request_observers[normalized] = observer
        try:
            yield
        finally:
            with self._lock:
                if self._request_observers.get(normalized) is observer:
                    self._request_observers.pop(normalized, None)

    def provider_for_token(self, token: str) -> str:
        with self._lock:
            provider_id = self._leases.get(token)
        if not provider_id:
            raise KeyError("Unknown or expired Claude Provider gateway token.")
        return provider_id

    def reasoning_effort_for_token(self, token: str) -> str:
        with self._lock:
            if token not in self._leases:
                raise KeyError("Unknown or expired Claude Provider gateway token.")
            return self._reasoning_efforts.get(token, "")

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=2)
        with self._lock:
            self._leases.clear()
            self._models.clear()
            self._reasoning_efforts.clear()
            self._request_indices.clear()
            self._request_observers.clear()

    def _observe(
        self,
        token: str,
        *,
        provider_id: str,
        protocol: str,
        requested_model: str,
        provider_model: str,
        reasoning_effort: str,
        payload: dict[str, Any],
    ) -> None:
        with self._lock:
            index = self._request_indices.get(token, 0) + 1
            self._request_indices[token] = index
            observer = self._request_observers.get(token)
        if not callable(observer):
            return
        tools = payload.get("tools")
        observation = {
            "request_index": index,
            "request_api": "claude_messages",
            "provider_id": provider_id,
            "provider_protocol": protocol,
            "requested_model": requested_model,
            "provider_model": provider_model,
            "reasoning_effort": reasoning_effort,
            "stream": bool(payload.get("stream")),
            "message_count": len(payload.get("messages")) if isinstance(payload.get("messages"), list) else 0,
            "tool_count": len(tools) if isinstance(tools, list) else 0,
        }
        try:
            observer(observation)
        except Exception:
            logger.exception("Claude Provider gateway request observer failed")

    def _handler_type(self):
        class Handler(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            server_version = "AgentParkClaudeGateway/1"

            def do_POST(self) -> None:
                self.close_connection = True
                self._response_started = False
                try:
                    token, endpoint = self._route()
                    provider_id = self.server.gateway.provider_for_token(token)  # type: ignore[attr-defined]
                    reasoning_effort = self.server.gateway.reasoning_effort_for_token(token)  # type: ignore[attr-defined]
                    payload = self._read_payload()
                    if endpoint == "count_tokens":
                        self._count_tokens(provider_id)
                        return
                    self._messages(token, provider_id, reasoning_effort, payload)
                except KeyError as exc:
                    self._json_error(404, str(exc))
                except UpstreamHttpError as exc:
                    if not self._response_started:
                        self._raw_error(
                            exc.status,
                            exc.body,
                            exc.headers.get("content-type", "application/json"),
                        )
                    else:
                        try:
                            message = exc.body.decode("utf-8", errors="replace")
                        except AttributeError:
                            message = str(exc)
                        self._stream_error(message or str(exc))
                except (ValueError, RuntimeError) as exc:
                    if not self._response_started:
                        self._json_error(400, str(exc))
                    else:
                        self._stream_error(str(exc))
                except Exception as exc:
                    if not self._response_started:
                        self._json_error(500, f"{type(exc).__name__}: {exc}")
                    else:
                        self._stream_error(f"{type(exc).__name__}: {exc}")

            def _route(self) -> tuple[str, str]:
                path = urllib.parse.urlsplit(self.path).path
                parts = [urllib.parse.unquote(part) for part in path.split("/") if part]
                if len(parts) == 3 and parts[1:] == ["v1", "messages"]:
                    return parts[0], "messages"
                if len(parts) == 4 and parts[1:] == ["v1", "messages", "count_tokens"]:
                    return parts[0], "count_tokens"
                raise ValueError("Claude Provider gateway accepts only /{token}/v1/messages endpoints.")

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
                try:
                    payload = json.loads(self.rfile.read(length).decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    raise ValueError("Request body must be UTF-8 JSON.") from exc
                if not isinstance(payload, dict):
                    raise ValueError("Request body must be a JSON object.")
                return payload

            def _messages(
                self,
                token: str,
                provider_id: str,
                reasoning_effort: str,
                payload: dict[str, Any],
            ) -> None:
                config = ConfigLoader().get_provider_config(provider_id)
                model = resolve_provider_model(config, self.server.gateway._models[token])
                config["model"] = model
                if not model:
                    raise ValueError(f"Provider {provider_id!r} has no model.")
                requested_model = str(payload.get("model") or "").strip()
                protocol = provider_protocol(config)
                request_payload = dict(payload)
                request_payload["model"] = model
                if reasoning_effort:
                    _validate_provider_reasoning_effort(
                        config,
                        protocol=protocol,
                        reasoning_effort=reasoning_effort,
                    )
                    output_config = request_payload.get("output_config")
                    request_payload["output_config"] = {
                        **(output_config if isinstance(output_config, dict) else {}),
                        "effort": reasoning_effort,
                    }
                effective_effort = reasoning_effort
                if not effective_effort:
                    output_config = request_payload.get("output_config")
                    effective_effort = (
                        str(output_config.get("effort") or "").strip()
                        if isinstance(output_config, dict)
                        else ""
                    )
                self.server.gateway._observe(  # type: ignore[attr-defined]
                    token,
                    provider_id=provider_id,
                    protocol=protocol,
                    requested_model=requested_model,
                    provider_model=model,
                    reasoning_effort=effective_effort,
                    payload=request_payload,
                )
                result = dispatch_messages(config, request_payload)
                if result.stream is not None:
                    self.send_response(200)
                    self.send_header("Content-Type", result.content_type)
                    self.send_header("Cache-Control", "no-cache")
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self._response_started = True
                    for frame in result.stream:
                        self.wfile.write(frame)
                        self.wfile.flush()
                    return
                if result.json_body is None:
                    raise RuntimeError("Gateway dispatch returned no JSON body.")
                self._json_response(result.status, result.json_body)

            def _count_tokens(self, provider_id: str) -> None:
                config = ConfigLoader().get_provider_config(provider_id)
                if provider_protocol(config) != "anthropic":
                    raise ValueError(
                        "Claude count_tokens is available only for native Anthropic Messages Providers."
                    )
                raise ValueError("Claude count_tokens forwarding is not implemented.")

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
                self._json_response(
                    status,
                    {"type": "error", "error": {"type": "agentpark_gateway_error", "message": str(message)}},
                )

            def _raw_error(self, status: int, body: bytes, content_type: str) -> None:
                self.send_response(status)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Connection", "close")
                self.end_headers()
                self._response_started = True
                self.wfile.write(body)

            def _stream_error(self, message: str) -> None:
                try:
                    body = json.dumps(
                        {"type": "error", "error": {"type": "api_error", "message": message}},
                        ensure_ascii=False,
                        separators=(",", ":"),
                    )
                    self.wfile.write(f"event: error\ndata: {body}\n\n".encode("utf-8"))
                    self.wfile.flush()
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, _format: str, *_args: object) -> None:
                return

        return Handler


def _validate_provider_reasoning_effort(
    config: dict[str, Any],
    *,
    protocol: str,
    reasoning_effort: str,
) -> None:
    if protocol not in {"responses", "anthropic"}:
        return
    features = config.get("features")
    reasoning = features.get("reasoning_effort") if isinstance(features, dict) else None
    values = reasoning.get("values") if isinstance(reasoning, dict) else None
    supported = {
        str(value or "").strip()
        for value in values
        if str(value or "").strip()
    } if isinstance(values, list) else set()
    if supported and reasoning_effort not in supported:
        raise ValueError(
            f"Provider reasoning_effort must be one of {sorted(supported)!r}; "
            f"got {reasoning_effort!r}."
        )


__all__ = ["ClaudeGatewayLease", "ClaudeProviderGateway"]
