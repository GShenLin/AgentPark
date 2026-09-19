from __future__ import annotations

import asyncio
import json
import logging
import re
import secrets
import time
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from fastapi import HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from .contracts import Signal
from .identity import DeviceIdentity, peer_id, verify, verify_signal
from .portal_auth import BOARD_CONNECTION_SECONDS, COOKIE, SESSION_SECONDS, PortalAuth
from .ice import TurnIssuer


LOGGER = logging.getLogger(__name__)


def register_portal_routes(app, registry, signing_identity: DeviceIdentity, password: str, web_root: Path | None, turn: TurnIssuer):
    auth = PortalAuth(password)

    @app.post("/portal/api/login")
    async def login(request: Request):
        auth.require_origin(request)
        raw = bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw) > 4096:
                raise HTTPException(413, "Login request is too large.")
        try:
            body = json.loads(raw)
            if set(body) != {"password"} or not isinstance(body["password"], str):
                raise ValueError("Invalid login request.")
        except (ValueError, TypeError) as exc:
            raise HTTPException(400, "Invalid login request.") from exc
        token = auth.login(body["password"], request.client.host)
        response = Response(status_code=204)
        local = request.url.hostname in {"127.0.0.1", "localhost", "::1"}
        response.set_cookie(COOKIE, token, max_age=SESSION_SECONDS, httponly=True, secure=not local, samesite="strict", path="/")
        response.headers["Cache-Control"] = "no-store"
        return response

    @app.get("/portal/api/devices")
    async def devices(request: Request, response: Response):
        auth.require_session(request)
        response.headers["Cache-Control"] = "no-store"
        return {"devices": registry.snapshot()}

    @app.post("/portal/api/logout")
    async def logout(request: Request):
        auth.require_origin(request)
        session = auth.sessions.pop(request.cookies.get(COOKIE, ""), None)
        if session:
            for browser in list(session.browser_ids):
                socket = registry.browsers.get(browser)
                if socket:
                    await socket.close(code=1000)
        response = Response(status_code=204)
        response.delete_cookie(COOKIE, path="/")
        return response

    @app.websocket("/portal/connect")
    async def connect(socket: WebSocket):
        try:
            auth.require_origin(socket)
            session = auth.require_session(socket)
            if len(session.browser_ids) >= 8:
                raise HTTPException(429, "Too many open Boards.")
        except HTTPException:
            await socket.close(code=1008)
            return
        await socket.accept()
        browser = None
        try:
            challenge = secrets.token_hex(32)
            await socket.send_json({"kind": "challenge", "challenge": challenge})
            raw = await asyncio.wait_for(socket.receive_text(), 10)
            if len(raw) > 2048:
                raise ValueError("Invalid browser proof size.")
            proof = json.loads(raw)
            if set(proof) != {"public_key", "signature"}:
                raise ValueError("Invalid browser proof.")
            verify(proof["public_key"], proof["signature"], {"challenge": challenge})
            browser = peer_id(proof["public_key"])
            if browser in registry.browsers or browser in registry.devices:
                raise ValueError("Browser identity is already connected.")
            if len(session.browser_ids) >= 8:
                raise ValueError("Too many open Boards.")
            registry.browsers[browser] = socket
            registry.browser_locks[browser] = asyncio.Lock()
            session.browser_ids.add(browser)
            connection_expires_at = min(session.expires_at, int(time.time()) + BOARD_CONNECTION_SECONDS)
            await registry.send_browser(browser, {"kind": "ready", "peer_id": browser,
                                                 "ice": turn.issue(browser, expires_at=connection_expires_at).model_dump()})
            count = 0
            while True:
                remaining = connection_expires_at - time.time()
                if remaining <= 0:
                    break
                raw = await asyncio.wait_for(socket.receive_text(), remaining)
                count += 1
                if len(raw.encode()) > 70000 or count > 20:
                    raise ValueError("Browser signaling limit exceeded.")
                signal = Signal.model_validate_json(raw)
                if verify_signal(signal, signal.target) != browser or signal.kind != "offer":
                    raise ValueError("Browser must send its own signed offer.")
                target = registry.devices.get(signal.target)
                if target is None or not target.portal_board:
                    await registry.send_browser(browser, {"kind": "error", "error": "Device is offline or cloud Board access is disabled."})
                    continue
                previous = registry.browser_targets.get(browser)
                if previous and previous != signal.target:
                    raise ValueError("Open a separate Board session for another device.")
                registry.browser_targets[browser] = signal.target
                ticket = {"browser_id": browser, "target": signal.target, "session_id": signal.session_id,
                          "expires_at": connection_expires_at}
                ticket["signature"] = signing_identity.sign(ticket)
                await registry.send_device(signal.target, {"kind": "portal_signal", "signal": signal.model_dump(), "ticket": ticket})
            await socket.close(code=1000)
        except WebSocketDisconnect:
            pass
        except (ValueError, TypeError, KeyError, InvalidSignature, ValidationError, TimeoutError, ConnectionError) as exc:
            LOGGER.warning("Portal signaling ended: %s", exc)
            await socket.close(code=1008)
        finally:
            if browser and registry.browsers.get(browser) is socket:
                target = registry.browser_targets.pop(browser, None)
                registry.browsers.pop(browser)
                registry.browser_locks.pop(browser)
                session.browser_ids.discard(browser)
                if target in registry.devices:
                    try:
                        await registry.send_device(target, {"kind": "portal_close", "peer_id": browser})
                    except (ConnectionError, RuntimeError):
                        LOGGER.warning("Device disconnected before portal closure could be delivered.")

    if web_root is not None:
        web_root = web_root.resolve()
        if (web_root / "assets").is_dir():
            app.mount("/assets", StaticFiles(directory=web_root / "assets"), name="portal-assets")

        @app.get("/portal-sw.js")
        async def worker():
            path = web_root / "portal-sw.js"
            if not path.is_file():
                raise HTTPException(503, "Build and deploy the AgentPark frontend first.")
            return FileResponse(path, media_type="application/javascript", headers={"Cache-Control": "no-store", "Service-Worker-Allowed": "/"})

        async def index():
            path = web_root / "index.html"
            if not path.is_file():
                raise HTTPException(503, "Build and deploy the AgentPark frontend first.")
            html = path.read_text(encoding="utf-8").replace("<head>", '<head><meta name="agentpark-portal" content="1">', 1)
            return HTMLResponse(html, headers={"Cache-Control": "no-store", "Referrer-Policy": "same-origin", "X-Content-Type-Options": "nosniff"})

        app.get("/")(index)

        @app.get("/board/{device_id}")
        async def board(device_id: str):
            if not re.fullmatch(r"[a-f0-9]{64}", device_id):
                raise HTTPException(404, "Device not found.")
            return await index()

    return auth
