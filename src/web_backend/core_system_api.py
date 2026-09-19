import os
import subprocess
import threading
import uuid

from fastapi import HTTPException, Request

from src.provider_options import build_provider_support_list
from src.cli_commands.companion_restart import build_restart_command
from src.cli_commands.companion_restart import resolve_restart_script
from src.cli_commands.companion_restart import restart_script_label

from .domain_base import DomainBase
from .request_access import has_owner_access
from .runtime_paths import _get_runtime_root
from .system_file_api import FileSystemApiMixin


SERVER_INSTANCE_ID = uuid.uuid4().hex


class SystemApiDomain(FileSystemApiMixin, DomainBase):
    def server_status(self):
        return {"ok": True, "instance_id": SERVER_INSTANCE_ID, "pid": os.getpid()}

    def checkpoint_restart(self, request: Request):
        if not has_owner_access(request):
            raise HTTPException(status_code=403, detail="restart checkpoint is only available locally")
        try:
            return self.core.restart_recovery.capture_running_nodes()
        except Exception as e:
            raise HTTPException(status_code=409, detail=str(e))

    def restart_server(self):
        runtime_root = _get_runtime_root()
        try:
            restart_path = resolve_restart_script(runtime_root)
            restart_env = dict(os.environ, AGENTPARK_RESTART_LISTENER="1")
            if os.name == "nt":
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "AgentPark Restart", restart_path],
                    cwd=runtime_root,
                    close_fds=True,
                    env=restart_env,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                log_dir = os.path.join(runtime_root, ".runtime")
                os.makedirs(log_dir, exist_ok=True)
                with open(os.path.join(log_dir, "restart.log"), "ab", buffering=0) as log:
                    subprocess.Popen(
                        [*build_restart_command(restart_path), "server"],
                        cwd=runtime_root,
                        start_new_session=True,
                        env=restart_env,
                        stdin=subprocess.DEVNULL,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                    )
        except FileNotFoundError as e:
            raise HTTPException(status_code=404, detail=str(e))
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True, "script": restart_path, "label": restart_script_label(restart_path), "instance_id": SERVER_INSTANCE_ID}

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
                include_private=has_owner_access(request),
            )
        }


__all__ = ["SystemApiDomain"]
