from __future__ import annotations

import json
import logging
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable

from .protocol import (
    DISCOVERY_HOST,
    DISCOVERY_PATH,
    DISCOVERY_PORT,
    ProtocolError,
    decode_json_object,
    normalize_server_origin,
    origins_equal,
)


MAX_DISCOVERY_BODY_BYTES = 64 * 1024
ConfigureServer = Callable[[str], object]


class DiscoveryServer:
    def __init__(
        self,
        configure_server: ConfigureServer,
        *,
        host: str = DISCOVERY_HOST,
        port: int = DISCOVERY_PORT,
        logger: logging.Logger | None = None,
    ) -> None:
        self._configure_server = configure_server
        self._host = host
        self._port = int(port)
        self._logger = logger or logging.getLogger(__name__)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def address(self) -> tuple[str, int]:
        if self._server is None:
            return self._host, self._port
        host, port = self._server.server_address[:2]
        return str(host), int(port)

    def start(self) -> None:
        if self._server is not None:
            return
        handler = _handler_type(self._configure_server, self._logger)
        server = ThreadingHTTPServer((self._host, self._port), handler)
        server.daemon_threads = True
        thread = threading.Thread(target=server.serve_forever, name="remote-discovery", daemon=True)
        self._server = server
        self._thread = thread
        thread.start()
        self._logger.info("Local Remote discovery listening on http://%s:%d%s", *self.address, DISCOVERY_PATH)

    def stop(self) -> None:
        server = self._server
        thread = self._thread
        self._server = None
        self._thread = None
        if server is None:
            return
        server.shutdown()
        server.server_close()
        if thread is not None:
            thread.join(timeout=5)


def _handler_type(configure_server: ConfigureServer, logger: logging.Logger):
    class DiscoveryRequestHandler(BaseHTTPRequestHandler):
        server_version = "AgentParkRemote/1"

        def do_OPTIONS(self) -> None:
            origin = self.headers.get("Origin", "")
            try:
                normalized_origin = normalize_server_origin(origin)
            except ProtocolError as exc:
                self._send_json(HTTPStatus.FORBIDDEN, {"ok": False, "error": str(exc)}, "null")
                return
            self._send_json(HTTPStatus.NO_CONTENT, None, normalized_origin)

        def do_POST(self) -> None:
            origin = self.headers.get("Origin", "")
            response_origin = "null"
            try:
                normalized_origin = normalize_server_origin(origin)
                response_origin = normalized_origin
                if self.path != DISCOVERY_PATH:
                    raise _HttpFailure(HTTPStatus.NOT_FOUND, "discovery route not found")
                content_length = _content_length(self.headers.get("Content-Length"))
                if content_length > MAX_DISCOVERY_BODY_BYTES:
                    raise _HttpFailure(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "discovery request body is too large")
                payload = decode_json_object(self.rfile.read(content_length), "discovery request")
                server_url = payload.get("server_url")
                normalized_server = normalize_server_origin(server_url)
                if not origins_equal(normalized_origin, normalized_server):
                    raise _HttpFailure(
                        HTTPStatus.FORBIDDEN,
                        "the AgentPark address must match the browser page origin",
                    )
                configure_server(normalized_server)
                self._send_json(
                    HTTPStatus.OK,
                    {"ok": True, "server_url": normalized_server},
                    response_origin,
                )
            except _HttpFailure as exc:
                self._send_json(exc.status, {"ok": False, "error": exc.message}, response_origin)
            except ProtocolError as exc:
                self._send_json(HTTPStatus.BAD_REQUEST, {"ok": False, "error": str(exc)}, response_origin)
            except Exception as exc:
                logger.exception("Failed to configure AgentPark server through local discovery")
                self._send_json(
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                    {"ok": False, "error": f"failed to configure AgentPark server: {type(exc).__name__}: {exc}"},
                    response_origin,
                )

        def _send_json(self, status: HTTPStatus, payload: dict | None, origin: str) -> None:
            body = b"" if payload is None else json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(int(status))
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Access-Control-Allow-Methods", "POST, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.send_header("Access-Control-Allow-Private-Network", "true")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            if body:
                self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:
            logger.debug("Discovery HTTP: " + format, *args)

    return DiscoveryRequestHandler


class _HttpFailure(Exception):
    def __init__(self, status: HTTPStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


def _content_length(value: str | None) -> int:
    if value is None:
        raise ProtocolError("Content-Length is required")
    try:
        length = int(value)
    except ValueError as exc:
        raise ProtocolError("Content-Length must be an integer") from exc
    if length < 0:
        raise ProtocolError("Content-Length must not be negative")
    return length
