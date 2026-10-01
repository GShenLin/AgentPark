"""Persistent connection settings and a single owner for the worker lifecycle."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field
from src.file_transaction import atomic_write_text

from .client import RemoteWorkerClient
from .cloud import CloudRemoteWorker
from .endpoint import resolve_endpoint
from .identity import IdentityStore, WorkerConfiguration
from src.remote_workspace.operations import WorkspaceOperationRegistry, validate_working_path


class RemoteSettings(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    server_address: str = Field(default="203.0.113.10", min_length=1)
    display_name: str = Field(min_length=1, max_length=100)
    workspace: str = Field(min_length=1)


def load_settings(path: Path, defaults: RemoteSettings) -> RemoteSettings:
    if not path.exists():
        return defaults
    return RemoteSettings.model_validate_json(path.read_text(encoding="utf-8"))


class WorkerLauncher:
    def __init__(self, state: Path, logger):
        self.state = state
        self.logger = logger
        self.status = "尚未连接"
        self.thread = None
        self.worker = None
        self.stopped = threading.Event()

    def start(self, settings: RemoteSettings):
        if self.thread and self.thread.is_alive():
            raise RuntimeError("请先断开当前连接，再保存并连接。")
        workspace = validate_working_path(settings.workspace)
        atomic_write_text(str(self.state / "settings.json"), settings.model_dump_json(indent=2))
        self.stopped.clear()
        self.thread = threading.Thread(target=self._run, args=(settings, workspace), name="remote-connection", daemon=True)
        self.thread.start()

    def _status(self, text):
        self.status = text

    def _run(self, settings, workspace):
        try:
            self.status = "正在探测目标 AgentPark 的登记入口…"
            endpoint = resolve_endpoint(settings.server_address)
            if self.stopped.is_set():
                return
            operations = WorkspaceOperationRegistry()
            if endpoint.kind == "coordinator":
                worker = CloudRemoteWorker(self.state, endpoint.origin, settings.display_name, workspace, operations, self._status)
                self.worker = worker
                if self.stopped.is_set():
                    worker.stop()
                self.status = f"正在向鉴权中心 {endpoint.origin} 登记"
                asyncio.run(worker.run())
            else:
                store = IdentityStore(self.state / "identity.json")
                config = WorkerConfiguration(store, store.load_or_create())
                config.configure_server(endpoint.origin)
                worker = RemoteWorkerClient(config, operations, workspace_path=workspace,
                                            display_name=settings.display_name, logger=self.logger,
                                            status_callback=self._status)
                self.worker = worker
                if self.stopped.is_set():
                    worker.stop()
                self.status = f"正在向 AgentPark {endpoint.origin} 登记"
                worker.run_forever()
        except Exception as exc:
            self.status = f"连接失败：{exc}"
            self.logger.exception("Remote connection failed")
        finally:
            self.worker = None
            if self.stopped.is_set():
                self.status = "已断开"

    def stop(self):
        self.stopped.set()
        self.status = "正在断开连接…"
        if self.worker is not None:
            # stop() may wait for HTTP polls. Never block the settings window.
            threading.Thread(target=self.worker.stop, name="remote-stop", daemon=True).start()


def show_settings(launcher: WorkerLauncher, settings: RemoteSettings):
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("AgentPark Remote")
    root.geometry("640x300")
    frame = ttk.Frame(root, padding=20)
    frame.pack(fill="both", expand=True)
    frame.columnconfigure(1, weight=1)
    values = {}
    for row, (field, label) in enumerate((("display_name", "设备名称"), ("server_address", "服务器 IP / 地址"), ("workspace", "默认工作目录"))):
        values[field] = tk.StringVar(value=getattr(settings, field))
        ttk.Label(frame, text=label).grid(row=row, column=0, sticky="w", pady=8)
        ttk.Entry(frame, textvariable=values[field]).grid(row=row, column=1, sticky="ew", padx=10)

    def folder():
        path = filedialog.askdirectory(parent=root, initialdir=values["workspace"].get())
        if path:
            values["workspace"].set(path)
    ttk.Button(frame, text="选择", command=folder).grid(row=2, column=2)
    status = tk.StringVar(value="准备连接")
    ttk.Label(frame, textvariable=status, wraplength=580).grid(row=3, column=0, columnspan=3, sticky="w", pady=12)

    def connect():
        try:
            launcher.start(RemoteSettings(**{key: value.get().strip() for key, value in values.items()}))
        except Exception as exc:
            messagebox.showerror("连接失败", str(exc), parent=root)
    ttk.Button(frame, text="保存并连接", command=connect).grid(row=4, column=0, pady=8)
    ttk.Button(frame, text="断开连接", command=launcher.stop).grid(row=4, column=1, sticky="w")
    ttk.Label(frame, text="先探测目标 8788；未提供 AgentPark 登记服务时，连接该地址的鉴权中心。",
              wraplength=580).grid(row=5, column=0, columnspan=3, sticky="w")

    def refresh():
        status.set(launcher.status)
        root.after(500, refresh)
    def close():
        launcher.stop()
        root.destroy()
    root.protocol("WM_DELETE_WINDOW", close)
    root.after(0, connect)
    root.after(500, refresh)
    root.mainloop()
