"""Authenticated local WebSocket commands for the desktop tray.

The tray has no HTTP client or business state: the backend owns the snapshot,
node resolution, restart checkpoint, and workspace shutdown operations.
"""
from __future__ import annotations

import asyncio
import json
import logging
import secrets
from pathlib import Path
from typing import Annotated, Literal

from fastapi import HTTPException, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, Field, StrictStr, TypeAdapter, ValidationError

from . import runtime_paths
from .desktop_tray_snapshot import build_tray_snapshot
from .node_window_api import NodeWindowApi


class TrayCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = Field(min_length=1, max_length=64)
    action: Literal["snapshot", "restart", "exit", "console"]


class OpenNodeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: StrictStr = Field(min_length=1, max_length=64)
    action: Literal["open-node"]
    graph_id: StrictStr = Field(min_length=1)
    node_id: StrictStr = Field(min_length=1)


COMMAND = TypeAdapter(Annotated[TrayCommand | OpenNodeCommand, Field(discriminator="action")])
logger = logging.getLogger(__name__)


class DesktopTrayApi:
    def __init__(self, core):
        self.core = core
        self.token = secrets.token_hex(32)

    async def connect(self, websocket: WebSocket) -> None:
        try:
            port = NodeWindowApi._require_local(websocket)
        except HTTPException:
            await websocket.close(code=1008)
            return
        await websocket.accept()
        try:
            # Authenticate in the first frame so the capability never enters URL logs.
            hello = await asyncio.wait_for(websocket.receive_json(), timeout=5)
            if not isinstance(hello, dict) or set(hello) != {"token"} or not isinstance(hello["token"], str) or not secrets.compare_digest(hello["token"], self.token):
                await websocket.close(code=1008)
                return
            await websocket.send_json({"ready": True})
            while True:
                command = COMMAND.validate_python(await websocket.receive_json())
                try:
                    result = await asyncio.to_thread(self.execute, command, websocket, port)
                except Exception as exc:
                    logger.exception("Desktop tray command failed: %s", command.action)
                    detail = str(exc.detail) if isinstance(exc, HTTPException) else str(exc)
                    await websocket.send_json({"id": command.id, "ok": False, "error": detail})
                else:
                    await websocket.send_json({"id": command.id, "ok": True, "result": result})
        except WebSocketDisconnect:
            pass  # Normal host/server shutdown.
        except (ValidationError, json.JSONDecodeError, TimeoutError):
            await websocket.close(code=1008)

    def execute(self, command: TrayCommand | OpenNodeCommand, websocket: WebSocket, port: int) -> dict:
        if isinstance(command, OpenNodeCommand):
            return self.core.node_windows.open_local(command.node_id, command.graph_id, port)
        if command.action == "snapshot":
            return build_tray_snapshot(Path(runtime_paths._get_graphs_dir())).model_dump()
        if command.action == "restart":
            self.core.restart_recovery.capture_running_nodes()
            return self.core.system_api.restart_server()
        if command.action == "console":
            from src.companion_cli_window import (
                get_companion_cli_window_status, hide_companion_cli_window, show_companion_cli_window,
            )
            status = get_companion_cli_window_status()
            if status.visible:
                hide_companion_cli_window()
            else:
                show_companion_cli_window()
            return {"ok": True}
        if command.action == "exit":
            # Reuse the same whole-workspace shutdown used by Settings.
            return self.core.system_api.request_workspace_exit(websocket.app, reason="exit requested by tray")
        raise ValueError(f"Unsupported tray action: {command.action}")
