"""Own one local service, its installer, and shutdown; never adopt arbitrary PIDs."""
import json
import os
from pathlib import Path
import secrets
import subprocess
import threading
import time

from src.file_transaction import atomic_write_text
from src.harness.process import stop_process
from src.provider_auth.store import save_account
from src.providers.curl_transport import CurlHttpTransport, CurlTransportError
from .installation import install, installed, python_path, _flags


class WorkBuddyServiceManager:
    def __init__(self, root: Path):
        self.root = root
        self.runtime = root / ".runtime" / "workbuddy"
        self.private = root / ".auth" / "workbuddy-service"
        self.settings_path = self.private / "settings.json"
        self.lock = threading.RLock()
        self.process = None
        self.installer = None
        self.worker = None
        self.closing = False
        self.state = "stopped"
        self.error = ""
        self.settings = {"autoStart": False, "port": 18788}
        if self.settings_path.exists():
            self.settings = self._validate_settings(json.loads(self.settings_path.read_text(encoding="utf-8")))

    @staticmethod
    def _validate_settings(value: dict) -> dict:
        if (set(value) != {"autoStart", "port"} or type(value["autoStart"]) is not bool
                or type(value["port"]) is not int or not 1024 <= value["port"] <= 65535):
            raise ValueError("Invalid WorkBuddy service settings")
        return dict(value)

    def configure(self, auto_start: bool, port: int) -> dict:
        with self.lock:
            if self.state in {"installing", "starting", "running", "stopping"} and port != self.settings["port"]:
                raise RuntimeError("请先停止服务再修改端口。")
            self.settings = self._validate_settings({"autoStart": auto_start, "port": port})
            atomic_write_text(str(self.settings_path), json.dumps(self.settings), encoding="utf-8")
            return self.status()

    def status(self) -> dict:
        with self.lock:
            if self.process is not None and self.process.poll() is not None:
                self.error = f"WorkBuddy 服务退出（代码 {self.process.returncode}），请查看服务日志。"
                self.state = "failed"
                self.process = None
            return {"state": self.state, "installed": installed(self.runtime),
                    "error": self.error, **self.settings,
                    "baseUrl": f"http://127.0.0.1:{self.settings['port']}/v1",
                    "logPath": str(self.runtime / "logs")}

    def begin(self, operation: str) -> dict:
        with self.lock:
            self.status()
            if self.closing or (self.worker and self.worker.is_alive()):
                raise RuntimeError("WorkBuddy 服务操作正在进行。")
            if operation == "install" and self.process is not None:
                raise RuntimeError("请先停止服务再安装依赖。")
            if operation == "start" and self.process is not None:
                return self.status()
            self.state = {"install": "installing", "start": "starting", "stop": "stopping"}[operation]
            self.error = ""
            self.worker = threading.Thread(target=self._operate, args=(operation,), daemon=True)
            self.worker.start()
            return self.status()

    def _operate(self, operation: str):
        try:
            if operation == "install":
                install(self.runtime, self.runtime / "logs" / "install.log", self._run_install)
                self._credentials()
                state = "stopped"
            elif operation == "start":
                self._start()
                state = "running"
            else:
                self._stop()
                state = "stopped"
            with self.lock:
                self.state = state
        except Exception as exc:
            with self.lock:
                self.state = "failed"
                self.error = str(exc)

    def _run_install(self, command: list[str], log):
        with self.lock:
            if self.closing:
                raise RuntimeError("WorkBuddy installation cancelled during shutdown")
            child = subprocess.Popen(command, stdout=log, stderr=log, creationflags=_flags(), start_new_session=os.name != "nt")
            self.installer = child
        try:
            code = child.wait(timeout=600)
            if code:
                raise RuntimeError(f"WorkBuddy 安装失败（代码 {code}），请查看 install.log。")
        finally:
            if child.poll() is None:
                stop_process(child)
            with self.lock:
                self.installer = None

    def _credentials(self) -> str:
        self.private.mkdir(parents=True, exist_ok=True)
        path = self.private / "gateway-key"
        if not path.exists():
            descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(secrets.token_urlsafe(48))
        key = path.read_text(encoding="utf-8").strip()
        if not key:
            raise RuntimeError("WorkBuddy gateway credential is empty")
        save_account("workbuddy", kind="api_key", credential={"apiKey": key},
                     identity="agentpark-local-service", alias="AgentPark 本机 WorkBuddy 服务", activate=False)
        return key

    def _start(self):
        executable = python_path(self.runtime)
        if not installed(self.runtime):
            raise RuntimeError("请先安装 WorkBuddy 服务依赖。")
        key = self._credentials()
        instance = secrets.token_hex(16)
        logs = self.runtime / "logs"
        logs.mkdir(parents=True, exist_ok=True)
        with self.lock:
            if self.closing:
                raise RuntimeError("AgentPark 正在关闭。")
            with (logs / "service.log").open("a", encoding="utf-8") as log:
                self.process = subprocess.Popen(
                    [str(executable), str(Path(__file__).with_name("service_process.py")),
                     "--root", str(self.root), "--port", str(self.settings["port"]), "--instance", instance],
                    stdin=subprocess.PIPE, stdout=log, stderr=log, creationflags=_flags(),
                    start_new_session=os.name != "nt",
                )
            child = self.process
        transport = CurlHttpTransport()
        for _ in range(60):
            if self.closing or child.poll() is not None:
                break
            try:
                result = transport.request(url=f"http://127.0.0.1:{self.settings['port']}/workbuddy/health",
                    headers={"Authorization": "Bearer " + key}, timeout_sec=1, follow_redirects=False)
                if result.status_code == 200 and result.json() == {"service": "agentpark-workbuddy", "ready": True, "instance": instance}:
                    return
            except CurlTransportError:
                pass  # Readiness retries are bounded; failure is reported below.
            except ValueError:
                break  # A foreign/malformed health response cannot identify this child.
            time.sleep(.25)
        self._stop()
        raise RuntimeError("WorkBuddy 服务未能启动，请检查端口占用和 service.log。")

    def _stop(self):
        with self.lock:
            child = self.process
        if child is not None:
            if child.stdin:
                child.stdin.close()
            try:
                child.wait(timeout=15)
            except subprocess.TimeoutExpired:
                stop_process(child)
                raise RuntimeError("WorkBuddy 服务未能及时退出，已终止；正在运行的请求可能失败。")
            finally:
                with self.lock:
                    if child.poll() is not None:
                        self.process = None

    def startup(self):
        if self.settings["autoStart"]:
            self.begin("start")

    def close(self):
        with self.lock:
            self.closing = True
            installer, worker = self.installer, self.worker
        if installer is not None and installer.poll() is None:
            stop_process(installer)
        if worker is not None:
            worker.join(timeout=20)
            if worker.is_alive():
                raise RuntimeError("WorkBuddy service operation did not finish during shutdown")
        self._stop()
