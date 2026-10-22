"""Windows desktop host startup, after the HTTP listener is actually ready."""
import os
import subprocess
from pathlib import Path

import uvicorn

from src.workspace_settings import get_workspace_root


def launch_desktop_tray(port: int, token: str) -> None:
    root = Path(get_workspace_root())
    host = root / "desktop" / "node-window"
    executable = host / "node_modules" / "electron" / "dist" / "electron.exe"
    if not executable.is_file():
        raise RuntimeError("Desktop runtime missing; run npm ci --prefix desktop/node-window")
    logs = root / ".runtime" / "node-windows"
    logs.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.pop("ELECTRON_RUN_AS_NODE", None)
    with (logs / "host.log").open("ab") as log:
        subprocess.Popen(
            [str(executable), str(host), "--tray", f"--origin=http://127.0.0.1:{port}", f"--token={token}"],
            cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW | subprocess.DETACHED_PROCESS,
            close_fds=True,
        )


class DesktopServer(uvicorn.Server):
    async def startup(self, sockets=None) -> None:
        await super().startup(sockets=sockets)
        if self.started and os.name == "nt":
            # The app is fully initialized and the socket is accepting connections.
            app = self.config.app
            launch_desktop_tray(self.config.port, app.state.desktop_tray.token)
