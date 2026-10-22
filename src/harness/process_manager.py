"""Node-scoped process lifecycle, independent of native conversation persistence."""
from __future__ import annotations

import atexit
from dataclasses import dataclass, field, replace
from pathlib import Path
import threading

from src.runtime_cancellation import CancellationSignal, CombinedCancellationSource, raise_if_cancel_requested
from .contracts import HarnessAdapter, HarnessContext
from .install_manager import runtime_lease, install_root
from .file_lock import file_lease
from .registry import create_adapter


@dataclass
class _Process:
    harness_id: str
    adapter: HarnessAdapter
    operation: threading.Lock = field(default_factory=threading.Lock)
    stop_operation: threading.Lock = field(default_factory=threading.Lock)
    guard: threading.RLock = field(default_factory=threading.RLock)
    cancel: CancellationSignal = field(default_factory=CancellationSignal)
    stopping: bool = False
    state: str = "stopped"
    error: str = ""
    context: HarnessContext | None = None
    wanted: bool = False
    installation_lease: object = None


class HarnessProcesses:
    _instance = None
    _lock = threading.RLock()

    def __init__(self):
        self.processes: dict[Path, _Process] = {}
        self.lock = threading.RLock()

    @classmethod
    def instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
                atexit.register(cls._instance.close_all)
            return cls._instance

    def _entry(self, harness_id, directory):
        key = Path(directory).resolve()
        with self.lock:
            entry = self.processes.get(key)
            if entry is None:
                entry = self.processes[key] = _Process(harness_id, create_adapter(harness_id))
            elif entry.harness_id != harness_id:
                raise ValueError("Stop and remove the old Harness process before changing node type.")
            return entry

    def status(self, directory):
        with self.lock:
            entry = self.processes.get(Path(directory).resolve())
        if entry is None:
            return {"state": "stopped", "error": ""}
        with entry.guard:
            if entry.state == "ready" and not entry.adapter.is_alive():
                entry.state, entry.error = "error", "Harness process exited unexpectedly."
            return {"state": entry.state, "error": entry.error}

    def execute(self, harness_id: str, context: HarnessContext, text: str | None = None, *, _restore=False):
        entry = self._entry(harness_id, context.node_directory)
        with entry.guard:
            if _restore and not entry.wanted:
                return None
            if entry.stopping:
                raise RuntimeError("Harness process is stopping.")
            generation = entry.cancel
            entry.wanted = True
            entry.context = replace(context, values={key: value for key, value in context.values.items()
                if key in {"graph_id", "node_instance_id", "node_id", "access_role", "provider_id", "model",
                           "working_path", "instruction", "timeout_seconds", "reasoning_effort", "sandbox",
                           "permission_mode", "web_search", "native_mode", "native_auto_approve",
                           "agent_mode", "inherit_mcp_servers", "command"}})
        source = CombinedCancellationSource((generation,
            context.values.get("cancel_event") or context.values.get("cancel_check")))
        context = replace(context, values={**context.values, "cancel_event": source})
        while not entry.operation.acquire(timeout=0.1):
            raise_if_cancel_requested(source)
        try:
            raise_if_cancel_requested(source)
            with runtime_lease(harness_id):
                with entry.guard:
                    entry.state, entry.error = "starting", ""
                if entry.installation_lease is None:
                    lease = file_lease(install_root(harness_id).parent / f"{harness_id}.lock", exclusive=False)
                    lease.__enter__()
                    entry.installation_lease = lease
                entry.adapter.prepare(context)
                raise_if_cancel_requested(source)
                if text is None:
                    return None
                with entry.guard:
                    entry.state = "running"
                return entry.adapter.run(text, context)
        except BaseException as exc:
            with entry.guard:
                entry.state, entry.error = "error", str(exc)
            self._close(entry)
            raise
        finally:
            with entry.guard:
                if entry.stopping:
                    entry.state = "stopping"
                elif entry.state != "error":
                    entry.state = "ready" if entry.adapter.is_alive() else "stopped"
            entry.operation.release()

    def stop(self, directory, *, for_update=False):
        with self.lock:
            entry = self.processes.get(Path(directory).resolve())
        if entry is None:
            return
        with entry.stop_operation:
            with entry.guard:
                if not for_update:
                    entry.wanted = False
                entry.stopping, entry.state = True, "stopping"
                entry.cancel.set()
            with entry.operation:
                try:
                    self._close(entry)
                except BaseException as exc:
                    with entry.guard:
                        entry.state, entry.error = "error", str(exc)
                    raise
                else:
                    with entry.guard:
                        entry.state, entry.error = "stopped", ""
                finally:
                    with entry.guard:
                        entry.cancel = CancellationSignal()
                        entry.stopping = False

    @staticmethod
    def _close(entry):
        entry.adapter.close()
        if entry.installation_lease is not None:
            entry.installation_lease.__exit__(None, None, None)
            entry.installation_lease = None

    def close_all(self, harness_id=None):
        with self.lock:
            paths = [path for path, entry in self.processes.items()
                     if harness_id is None or entry.harness_id == harness_id]
        for path in paths:
            self.stop(path)

    def list(self, harness_id=None):
        with self.lock:
            entries = list(self.processes.items())
        rows = []
        for path, entry in entries:
            if harness_id is not None and entry.harness_id != harness_id:
                continue
            status = self.status(path)
            if status["state"] == "stopped" or entry.context is None:
                continue
            values = entry.context.values
            rows.append({"harness_id": entry.harness_id, "graph_id": values.get("graph_id", "default"),
                         "node_id": values.get("node_instance_id") or values.get("node_id") or path.name,
                         **status})
        return rows

    def suspend_type(self, harness_id):
        with self.lock:
            paths = [path for path, entry in self.processes.items() if entry.harness_id == harness_id
                     and entry.context is not None and entry.wanted]
        for path in paths:
            self.stop(path, for_update=True)
        return paths

    def restore(self, paths):
        failures = []
        for path in paths:
            with self.lock:
                entry = self.processes.get(path)
            if entry is None or not entry.wanted:
                continue
            try:
                self.execute(entry.harness_id, entry.context, _restore=True)
            except Exception as exc:
                failures.append({"node_id": path.name, "error": str(exc)})
        return failures

    def forget(self, directory):
        self.stop(directory)
        with self.lock:
            self.processes.pop(Path(directory).resolve(), None)
