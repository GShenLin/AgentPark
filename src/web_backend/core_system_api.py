import os
import subprocess
import threading

from fastapi import HTTPException, Request

from src.provider_options import build_provider_support_list

from .domain_base import DomainBase
from .runtime_paths import _get_runtime_root
from .system_file_api import FileSystemApiMixin


class SystemApiDomain(FileSystemApiMixin, DomainBase):
    def restart_server(self):
        runtime_root = _get_runtime_root()
        restart_path = os.path.join(runtime_root, "Restart.bat")
        if not os.path.isfile(restart_path):
            raise HTTPException(status_code=404, detail="Restart.bat not found")
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "AgentPark Restart", restart_path],
                    cwd=runtime_root,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                subprocess.Popen([restart_path], cwd=runtime_root, start_new_session=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    def exit_server(self, request: Request):
        exit_func = getattr(request.app.state, "request_workspace_exit", None)
        if not callable(exit_func):
            raise HTTPException(status_code=500, detail="workspace exit hook is not available")

        def request_exit() -> None:
            exit_func("exit requested by Settings")

        timer = threading.Timer(0.2, request_exit)
        timer.daemon = True
        timer.start()
        return {"ok": True}

    def list_providers(self):
        return {"providers": build_provider_support_list()}


__all__ = ["SystemApiDomain"]
