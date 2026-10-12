import json
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
from .strata import StrataAdapter


class LocalModelService:
    def __init__(self, workspace: Path):
        self.catalog = Catalog(workspace)
        self.logs = workspace / ".runtime" / "local-model"
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        self.processes: dict[str, subprocess.Popen] = {}

    def adapter(self, key: str):
        config = self.catalog.get(key)
        return StrataAdapter(config) if config["kind"] == "strata" else ComfyAdapter(config)

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
        python = self.python(adapter.config, required=False)
        result.update(python_path=python, python_exists=bool(python and Path(python).is_file()),
                      managed=self.managed(key))
        return result

    @staticmethod
    def python(config, required=True):
        if config["python_path"]:
            path = Path(config["python_path"])
        else:
            path = Path(config["install_path"]) / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        if required and not path.is_file():
            raise ValueError("未找到 Python 环境，请配置此服务实际使用的 Python 可执行文件")
        return str(path)

    def job(self, key):
        with self.lock:
            if key not in self.jobs:
                raise KeyError("操作记录不存在（服务重启后记录不保留）")
            return dict(self.jobs[key])

    def operate(self, key: str, operation: Operation):
        adapter = self.adapter(key)
        with self.lock:
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
            elif action == "load":
                result = adapter.load(operation.model_id)
            elif action == "unload":
                result = adapter.unload()
            else:
                result = adapter.import_model(operation.source_path, operation.category)
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
        if not status["installed"]:
            raise ValueError("安装目录不完整，请检查路径")
        # Refuse occupied ports even when the HTTP service is not a matching engine.
        import socket
        address = urlsplit(config["endpoint"])
        with socket.socket(socket.AF_INET6 if address.hostname == "::1" else socket.AF_INET) as sock:
            sock.settimeout(1)
            if sock.connect_ex((address.hostname, address.port)) == 0:
                raise RuntimeError("配置端口已被其他进程占用")
        command = adapter.command(self.python(config), model_id, address.port) + config["extra_args"]
        if address.hostname == "::1":
            command = ["::1" if x == "127.0.0.1" else x for x in command]
        self.logs.mkdir(parents=True, exist_ok=True)
        log = self.logs / (config["id"] + ".log")
        with log.open("ab") as output:
            proc = subprocess.Popen(command, cwd=config["install_path"], stdin=subprocess.DEVNULL,
                                    stdout=output, stderr=subprocess.STDOUT,
                                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        with self.lock:
            self.processes[config["id"]] = proc
        for _ in range(120):
            if proc.poll() is not None:
                raise RuntimeError(f"启动失败（退出码 {proc.returncode}），日志：{log}")
            http = adapter.http() if config["kind"] == "strata" else adapter.http
            health, _ = http.probe("/health" if config["kind"] == "strata" else "/system_stats")
            ready = (isinstance(health, dict) and (health.get("service") == "strata" if config["kind"] == "strata"
                     else "comfyui_version" in health.get("system", {})))
            if ready:
                return {"message": "服务已启动；模型由你手动加载", "log": str(log)}
            time.sleep(.5)
        raise RuntimeError(f"服务尚未就绪，进程仍在运行；请刷新检测或手动停止。日志：{log}")

    def stop(self, adapter):
        key = adapter.config["id"]
        proc = self.processes.get(key)
        if proc is None or proc.poll() is not None:
            raise RuntimeError("只能停止本次 AgentPark 运行期间由本模块启动的服务；外部启动的服务请在原入口停止")
        if adapter.config["kind"] == "comfyui":
            health, _ = adapter.http.probe("/system_stats")
            if health is not None:
                adapter.idle()
        else:
            status, _ = adapter.http().probe("/v1/status")
            if isinstance(status, dict) and status.get("activity", {}).get("in_flight", 0):
                raise RuntimeError("Strata 有任务正在执行或排队，请完成后再停止")
            if isinstance(status, dict) and status.get("loaded"):
                adapter.unload()
        proc.terminate()
        proc.wait(timeout=30)
        return {"message": "服务进程已停止"}
