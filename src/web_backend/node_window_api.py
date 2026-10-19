"""Launch a local node view and acknowledge renderer readiness, not just process creation."""
from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import HTTPException, Request, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, ConfigDict, StrictBool, ValidationError

from src.workspace_settings import get_workspace_root
from .request_access import is_local_request
from .node_window_alerts import NodeWindowAlerts


class FocusState(BaseModel):
    model_config = ConfigDict(extra='forbid')
    focused: StrictBool


class NodeWindowApi:
    def __init__(self, core: object):
        self.core = core
        self.alerts = NodeWindowAlerts(core.graph_events, self.open_local)

    @staticmethod
    def _require_local(request: Request | WebSocket) -> int:
        if not is_local_request(request) or getattr(request.state, "peer_principal", None) is not None:
            raise HTTPException(403, "节点悬浮窗只能在 AgentPark 所在电脑打开。")
        port = request.scope["server"][1]
        origin = request.headers.get("origin")
        if origin:
            try:
                parsed = urlsplit(origin)
                allowed = parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1", "::1"} and parsed.port == port
            except ValueError:
                allowed = False
            if not allowed:
                raise HTTPException(403, "Desktop launch requires the local AgentPark origin.")
        if request.headers.get("sec-fetch-site") == "cross-site":
            raise HTTPException(403, "Cross-site desktop launch is not allowed.")
        return port

    def status(self, request: Request) -> dict:
        self._require_local(request)
        return self.alerts.status()

    async def focus(self, websocket: WebSocket) -> None:
        try:
            self._require_local(websocket)
        except HTTPException:
            await websocket.close(code=1008)
            return
        connection_id = uuid.uuid4().hex
        await websocket.accept()
        try:
            while True:
                state = FocusState.model_validate(await websocket.receive_json())
                self.alerts.set_focused(connection_id, state.focused)
                await websocket.send_json({'focused': state.focused})
        except WebSocketDisconnect:
            pass  # Closing the browser releases foreground presence in finally.
        except (ValidationError, json.JSONDecodeError):
            await websocket.close(code=1008)
        finally:
            self.alerts.set_focused(connection_id, False)

    def open(self, node_id: str, request: Request, graph_id: str = "") -> dict:
        return self.open_local(node_id, graph_id, self._require_local(request))

    def open_local(self, node_id: str, graph_id: str, port: int) -> dict:
        graph, node, _, _ = self.core.node_ops._resolve_node_instance_folder(node_id, graph_id)
        if os.name != "nt":
            raise HTTPException(501, "当前节点悬浮窗宿主支持 Windows。")
        root = Path(get_workspace_root())
        host = root / "desktop" / "node-window"
        executable = host / "node_modules" / "electron" / "dist" / "electron.exe"
        if not executable.is_file():
            raise HTTPException(503, "节点窗口运行环境尚未安装，请运行 npm ci --prefix desktop/node-window。")
        receipts = root / ".runtime" / "node-windows"
        receipts.mkdir(parents=True, exist_ok=True)
        receipt_id = uuid.uuid4().hex
        receipt = receipts / f"{receipt_id}.json"
        env = dict(os.environ)
        env.pop("ELECTRON_RUN_AS_NODE", None)
        try:
            with (receipts / "host.log").open("ab") as log:
                subprocess.Popen(
                    [str(executable), str(host), f"--origin=http://127.0.0.1:{port}",
                     f"--graph={graph}", f"--node={node}", f"--receipt={receipt_id}"],
                    cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
                    creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
                    close_fds=True,
                )
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline:
                if receipt.exists():
                    result = json.loads(receipt.read_text(encoding="utf-8"))
                    if result.get("ok") is not True:
                        raise HTTPException(502, str(result.get("error") or "节点窗口未能加载。"))
                    return {"ok": True, "graph_id": graph, "node_id": node}
                time.sleep(0.1)
            raise HTTPException(504, "节点窗口未在 25 秒内就绪，请查看 .runtime/node-windows/host.log。")
        except OSError as exc:
            raise HTTPException(500, f"启动节点窗口失败：{exc}") from exc
        finally:
            receipt.unlink(missing_ok=True)
