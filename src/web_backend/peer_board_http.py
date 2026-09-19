from __future__ import annotations

import asyncio
import base64
import json
import time
from urllib.parse import unquote, urlsplit

from fastapi import HTTPException, Request

from src.peer_network.contracts import BoardHttpRequest
from src.peer_network.principal import CloudBoardAdministrator


MAX_HTTP_BODY = 4 * 1024 * 1024


def allowed_board_request(method: str, path: str) -> bool:
    if "\\" in path or any(part in {".", ".."} for part in path.split("/")):
        return False
    # This dispatcher is reachable only through an authenticated administrator's
    # device-bound Board ticket. Ordinary peers cannot issue Board HTTP calls.
    if method in {"GET", "POST", "PUT", "PATCH", "DELETE"} and path.startswith("/api/"):
        return True
    return method == "GET" and path.startswith("/memories/")


def result(status: int, body: bytes, headers: dict[str, str]) -> dict:
    return {"status": status, "headers": headers, "body": base64.b64encode(body).decode("ascii")}


class PeerBoardHttp:
    """Dispatch authenticated administrator requests without spoofing loopback origin."""

    def __init__(self, core, app):
        self.core = core
        self.app = app
        self.undo_owners: dict[str, tuple[str, float]] = {}

    async def __call__(self, browser_id: str, http: BoardHttpRequest) -> dict:
        url = urlsplit(http.path)
        path = unquote(url.path)
        if url.scheme or url.netloc or url.fragment or not allowed_board_request(http.method, path):
            return result(403, b'{"detail":"This endpoint is not available through the cloud Board."}', {"content-type": "application/json"})
        self.undo_owners = {token: owner for token, owner in self.undo_owners.items() if owner[1] > time.time()}
        undo_token = path.removeprefix("/api/undo/") if path.startswith("/api/undo/") else None
        if undo_token is not None and self.undo_owners.get(undo_token, (None, 0))[0] != browser_id:
            return result(403, b'{"detail":"Only deletions from this Board session can be undone."}', {"content-type": "application/json"})
        body = base64.b64decode(http.body, validate=True)
        if len(body) > MAX_HTTP_BODY:
            raise ValueError("Board request body exceeds 4 MiB.")
        headers = {key.lower(): value for key, value in http.headers.items()
                   if key.lower() in {"content-type", "last-event-id", "range"}}
        scope = {"type": "http", "asgi": {"version": "3.0", "spec_version": "2.3"},
                 "http_version": "1.1", "method": http.method, "scheme": "https", "path": path,
                 "raw_path": path.encode(), "query_string": url.query.encode(), "root_path": "",
                 "server": ("peer-board", 443), "client": ("portal:" + browser_id, 0),
                 "headers": [(key.encode(), value.encode()) for key, value in headers.items()],
                 "state": {"peer_principal": CloudBoardAdministrator(browser_id, "Cloud Board administrator")}}
        if path == "/api/app/events/stream":
            return await self.event_poll(Request(scope), headers.get("last-event-id"))
        status, response_headers, data = 500, {}, bytearray()
        received = False
        done = asyncio.Event()

        async def receive():
            nonlocal received
            if not received:
                received = True
                return {"type": "http.request", "body": body, "more_body": False}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message):
            nonlocal status, response_headers
            if message["type"] == "http.response.start":
                status = message["status"]
                response_headers = {key.decode().lower(): value.decode() for key, value in message["headers"]
                                    if key.decode().lower() in {"content-type", "content-disposition", "content-range", "accept-ranges"}}
            elif message["type"] == "http.response.body":
                data.extend(message.get("body", b""))
                if len(data) > MAX_HTTP_BODY:
                    raise ValueError("Board response exceeds 4 MiB. Narrow the request.")
                if not message.get("more_body", False):
                    done.set()

        async with asyncio.timeout(40):
            await self.app(scope, receive, send)
        if 200 <= status < 300:
            if undo_token is not None:
                self.undo_owners.pop(undo_token, None)
            if response_headers.get("content-type", "").startswith("application/json"):
                payload = json.loads(data)
                token = payload.get("undo_token") if isinstance(payload, dict) else None
                if isinstance(token, str) and token:
                    self.undo_owners[token] = (browser_id, time.time() + 3600)
        return result(status, bytes(data), response_headers)

    async def event_poll(self, request: Request, cursor: str | None) -> dict:
        if cursor is None:
            version = self.core.graph_events.get_global_version()
            event = {"event": "stream_snapshot", "stream_snapshot": True, "global_version": version}
        else:
            if not cursor.isdigit() or len(cursor) > 20:
                raise ValueError("Invalid Board event cursor.")
            version = int(cursor)
            event = await asyncio.to_thread(self.core.graph_events.wait_for_global_change, version, 15.0)
            if event is not None:
                version = int(event["global_version"])
                if event.get("event") != "stream_gap":
                    graph_id = str(event.get("graph_id") or self.core.default_graph_id)
                    try:
                        self.core.graph_api.require_graph_visible(graph_id, request)
                        if event.get("event") == "node_live":
                            node_id = str(event.get("node_instance_id") or event.get("node_id") or "")
                            self.core.node_ops.require_node_visible(node_id, graph_id, request)
                        event = self.core.graph_api.sanitize_graph_event_for_request(graph_id, event, request)
                        event["global_version"] = version
                    except HTTPException as exc:
                        if exc.status_code != 404:
                            raise
                        event = None
        data = f"id: {version}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n" if event is not None else ": keep-alive\n\n"
        return result(200, data.encode(), {"content-type": "text/event-stream", "x-peer-event-cursor": str(version)})
