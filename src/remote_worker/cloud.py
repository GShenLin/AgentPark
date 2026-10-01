"""Standalone execution host registered with the existing authentication center."""
from __future__ import annotations

import asyncio
import threading
from pathlib import Path
from urllib.parse import urlsplit

from src.peer_network.contracts import NetworkSettings
from src.peer_network.service import PeerNetworkService

from src.remote_workspace.operations import WorkspaceOperationRegistry
from src.remote_workspace.execution import WorkspaceExecutor


class CloudRemoteWorker:
    def __init__(self, state: Path, origin: str, name: str, workspace: str,
                 operations: WorkspaceOperationRegistry, status):
        self.operations = operations
        self.status = status
        self.stopped = threading.Event()
        self.executor = WorkspaceExecutor(operations)
        self.service = PeerNetworkService(state / "peer-network", self.reject_peer_call)
        self.service.store.settings = NetworkSettings(
            enabled=True, signaling_url=origin.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + "/connect",
            display_name=name, portal_board=False,
            stun_urls=[f"stun:{urlsplit(origin).hostname}:3478"],
        )
        self.worker_id = self.service.identity.peer_id
        self.service.remote.provider = lambda: [{
            "worker_id": self.worker_id, "display_name": name, "host_kind": "standalone",
            "workspace_path": workspace, "capabilities": list(operations.capabilities), "online": True,
        }]
        self.service.remote.dispatch = self.executor.dispatch

    async def reject_peer_call(self, grant, call):
        raise PermissionError("A Remote execution host only accepts workspace operations.")

    async def run(self):
        await self.service.start()
        try:
            while not self.stopped.is_set():
                state = self.service.enrollment_state
                text = {"pending": "等待鉴权中心确认接入", "rejected": "鉴权中心已拒绝接入",
                        "approved": "已登记到鉴权中心，可在各设备节点中选择", "disconnected": "正在连接鉴权中心"}[state]
                self.status(self.service.coordinator_error or text)
                await asyncio.sleep(.5)
        finally:
            self.executor.close()
            await self.service.stop()

    def stop(self):
        self.stopped.set()
