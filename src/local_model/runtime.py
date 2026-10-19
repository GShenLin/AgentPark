import os
import subprocess
import threading
import time
import uuid
from pathlib import Path
from urllib.parse import urlsplit

from .catalog import Catalog
from .comfyui import ComfyAdapter
from .contracts import Operation, ServiceConfig
from .generic import GenericAdapter
from .service_adapter import ModelServiceAdapter, ServiceAdapter
from .process import stop_process_tree
from .strata import StrataAdapter


class LocalModelService:
    def __init__(self, workspace: Path):
        self.catalog = Catalog(workspace)
        self.logs = workspace / ".runtime" / "local-model"
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.processes: dict[str, subprocess.Popen] = {}

    def adapter(self, key: str) -> ServiceAdapter:
        config = self.catalog.get(key)
        adapters = {None: GenericAdapter, "strata": StrataAdapter, "comfyui": ComfyAdapter}
        return adapters[config["kind"]](config)

    def list(self):
        with self.lock:
            return {"services": self.catalog.list(), "jobs": [dict(x) for x in self.jobs.values()]}

    def active(self, key):
        return any(j["service_id"] == key and j["state"] == "running" for j in self.jobs.values())

    def managed(self, key):
        proc = self.processes.get(key)
        return proc is not None and proc.poll() is None

    def save(self, config: ServiceConfig, key: str | None = None):
        with self.lock:
            if key and (self.active(key) or self.managed(key)):
                raise RuntimeError("请先完成当前操作并停止本模块启动的服务，再修改配置")
            return self.catalog.save(config, key)

    def remove(self, key):
        with self.lock:
            if self.active(key) or self.managed(key):
                raise RuntimeError("请先完成当前操作并停止本模块启动的服务，再移除登记")
            self.catalog.remove(key)
        return {"message": "已移除登记，安装文件和模型均保留"}

    def inspect(self, key):
        adapter = self.adapter(key)
        result = adapter.inspect()
        launch_issues = adapter.launch_issues()
        proc = self.processes.get(key)
        result.update(launchable=result["installed"] and not launch_issues, launch_issues=launch_issues,
                      actions=adapter.actions, managed=self.managed(key),
                      exit_code=proc.poll() if proc is not None else None)
        return result

    def job(self, key):
        with self.lock:
            if key not in self.jobs:
                raise KeyError("操作记录不存在（服务重启后记录不保留）")
            return dict(self.jobs[key])

    def operate(self, key: str, operation: Operation):
        with self.lock:
            adapter = self.adapter(key)
            if operation.action not in adapter.actions:
                raise ValueError("此服务未配置对应的模型管理能力")
            if self.active(key):
                raise RuntimeError("该服务已有操作正在执行")
            job_id = uuid.uuid4().hex
            job = {"id": job_id, "service_id": key, "action": operation.action,
                   "state": "running", "message": "正在执行…", "started_at": time.time()}
            self.jobs[job_id] = job
            # Keep a bounded history; preserve all running jobs.
            finished = [k for k, v in self.jobs.items() if v["state"] != "running"]
            for old in finished[:-50]:
                del self.jobs[old]
            threading.Thread(target=self._run, args=(adapter, operation, job_id), daemon=True).start()
            return dict(job)

    def _run(self, adapter, operation, job_id):
        try:
            action = operation.action
            if action == "start":
                result = self.start(adapter, operation.model_id)
            elif action == "stop":
                result = self.stop(adapter)
            elif isinstance(adapter, ModelServiceAdapter):
                if action == "load":
                    result = adapter.load(operation.model_id)
                elif action == "unload":
                    result = adapter.unload()
                else:
                    result = adapter.import_model(operation.source_path, operation.category)
            else:
                raise ValueError("此服务未配置对应的模型管理能力")
            update = {"state": "succeeded", "message": result["message"], "result": result}
        except Exception as exc:
            update = {"state": "failed", "message": str(exc)}
        with self.lock:
            self.jobs[job_id].update(update, finished_at=time.time())

    def start(self, adapter, model_id):
        config = adapter.config
        if self.managed(config["id"]):
            raise RuntimeError("该服务进程已启动，请刷新检测状态")
        status = adapter.inspect()
        if status["online"]:
            raise RuntimeError("服务已在线，无需重复启动")
        launch = adapter.launch(model_id)
        if not status["installed"]:
            raise ValueError("安装目录不完整，请检查路径")
        # Refuse occupied ports even when the HTTP service is not a matching engine.
        import socket
        if config["endpoint"]:
            address = urlsplit(config["endpoint"])
            port = address.port or (443 if address.scheme == "https" else 80)
            for family, socktype, proto, _, sockaddr in socket.getaddrinfo(
                    address.hostname, port, type=socket.SOCK_STREAM):
                with socket.socket(family, socktype, proto) as sock:
                    sock.settimeout(1)
                    if sock.connect_ex(sockaddr) == 0:
                        raise RuntimeError("配置端口已被其他进程占用")
        self.logs.mkdir(parents=True, exist_ok=True)
        log = self.logs / (config["id"] + ".log")
        with log.open("ab") as output:
            proc = subprocess.Popen(launch.command, cwd=launch.cwd, stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    start_new_session=os.name != "nt",
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        with self.lock:
            self.processes[config["id"]] = proc
        deadline = time.monotonic() + config["startup_timeout"]
        error = ""
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError(f"启动失败（退出码 {proc.returncode}），日志：{log}")
            ready, error = adapter.probe_ready()
            if ready is None:
                return {"message": "进程已启动；未配置就绪检测，请在服务入口确认可用性", "log": str(log)}
            if ready:
                if proc.poll() is not None:
                    raise RuntimeError(f"启动进程已退出（退出码 {proc.returncode}），日志：{log}")
                return {"message": "服务已启动，就绪检测通过", "log": str(log)}
            time.sleep(.5)
        raise RuntimeError(f"服务尚未就绪，进程仍在运行；请刷新检测或手动停止。检测：{error}。日志：{log}")

    def stop(self, adapter):
        key = adapter.config["id"]
        proc = self.processes.get(key)
        if proc is None or proc.poll() is not None:
            raise RuntimeError("只能停止本次 AgentPark 运行期间由本模块启动的服务；外部启动的服务请在原入口停止")
        adapter.prepare_stop()
        stop_process_tree(proc)
        return {"message": "服务进程已停止"}
