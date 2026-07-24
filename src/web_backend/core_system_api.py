import os
import subprocess
import threading

from fastapi import HTTPException, Request

from src.provider_options import build_provider_support_list
from src.cli_commands.companion_restart import build_restart_command
from src.cli_commands.companion_restart import resolve_restart_script
from src.cli_commands.companion_restart import restart_script_label

from .domain_base import DomainBase
from .request_access import is_local_request
from .runtime_paths import _get_runtime_root
from .system_file_api import FileSystemApiMixin


class SystemApiDomain(FileSystemApiMixin, DomainBase):
    def restart_server(self):
        runtime_root = _get_runtime_root()
        try:
            restart_path = resolve_restart_script(runtime_root)
            if os.name == "nt":
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "AgentPark Restart", restart_path],
                    cwd=runtime_root,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                subprocess.Popen(list(build_restart_command(restart_path)), cwd=runtime_root, start_new_session=True)
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "script": restart_path, "label": restart_script_label(restart_path)}

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

    def list_providers(self, request: Request = None):
        return {
            "providers": build_provider_support_list(
                include_private=is_local_request(request),
            )
        }


__all__ = ["SystemApiDomain"]
