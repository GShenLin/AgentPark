from __future__ import annotations

import asyncio
import json
import os
import socket
import sys
import threading
import time
import traceback
from datetime import datetime
from typing import Any, Callable

from src.workspace_settings import get_workspace_root, resolve_local_client_host


LIFECYCLE_LOG_FILENAME = "server-lifecycle.jsonl"


class RuntimeSupervisor:
    """Records server lifecycle and detects a live PID with a dead listener."""

    def __init__(self, *, probe_interval_seconds: float = 10.0, startup_grace_seconds: float = 5.0) -> None:
        self.probe_interval_seconds = probe_interval_seconds
        self.startup_grace_seconds = startup_grace_seconds
        self._lock = threading.RLock()
        self._stop = threading.Event()
        self._watchdog: threading.Thread | None = None
        self._host = ""
        self._port = 0
        self._listener_state: bool | None = None
        self._critical_threads: dict[str, tuple[threading.Thread, Callable[[], bool] | None]] = {}
        self._reported_dead_threads: set[str] = set()
        self._previous_thread_excepthook = threading.excepthook

    @property
    def log_path(self) -> str:
        return os.path.join(get_workspace_root(), ".runtime", LIFECYCLE_LOG_FILENAME)

    def configure_listener(self, host: str, port: int) -> None:
        with self._lock:
            self._host = resolve_local_client_host(host)
            self._port = int(port)
        self.record("listener_configured", host=host, probe_host=self._host, port=self._port)

    def start(self) -> None:
        with self._lock:
            if self._watchdog is not None and self._watchdog.is_alive():
                return
            self._stop.clear()
            threading.excepthook = self._thread_excepthook
            watchdog = threading.Thread(target=self._watchdog_loop, name="runtime-supervisor", daemon=True)
            self._watchdog = watchdog
            watchdog.start()
        self.record("supervisor_started", startup_grace_seconds=self.startup_grace_seconds)

    def stop(self, *, reason: str) -> None:
        self.record("supervisor_stop_requested", reason=reason)
        self._stop.set()
        watchdog = self._watchdog
        if watchdog is not None and watchdog is not threading.current_thread():
            watchdog.join(timeout=min(2.0, self.probe_interval_seconds + 0.5))
        with self._lock:
            self._watchdog = None
            if threading.excepthook == self._thread_excepthook:
                threading.excepthook = self._previous_thread_excepthook
        self.record("supervisor_stopped", reason=reason)

    def attach_asyncio_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        if getattr(loop, "_agentpark_supervision_attached", False):
            return
        previous = loop.get_exception_handler()

        def handle_exception(active_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            error = context.get("exception")
            self.record(
                "asyncio_unhandled_exception",
                level="error",
                message=str(context.get("message") or ""),
                exception_type=type(error).__name__ if error is not None else "",
                exception=str(error or ""),
                traceback="".join(traceback.format_exception(error)) if error is not None else "",
            )
            if previous is not None:
                previous(active_loop, context)
            else:
                active_loop.default_exception_handler(context)

        loop.set_exception_handler(handle_exception)
        setattr(loop, "_agentpark_supervision_attached", True)
        self.record("asyncio_exception_handler_attached", loop_type=type(loop).__name__)

    def register_critical_thread(
        self,
        name: str,
        thread: threading.Thread,
        *,
        expected_running: Callable[[], bool] | None = None,
    ) -> None:
        with self._lock:
            self._critical_threads[name] = (thread, expected_running)
            self._reported_dead_threads.discard(name)
        self.record("critical_thread_registered", thread_name=name, thread_ident=thread.ident)

    def record(self, event: str, *, level: str = "info", **fields: Any) -> None:
        payload = {
            "ts": datetime.now().astimezone().isoformat(timespec="milliseconds"),
            "monotonic_ns": time.monotonic_ns(),
            "event": event,
            "level": level,
            "pid": os.getpid(),
            "thread_name": threading.current_thread().name,
            "thread_ident": threading.get_ident(),
            **fields,
        }
        path = self.log_path
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, default=str) + "\n"
            with self._lock, open(path, "a", encoding="utf-8", newline="") as handle:
                handle.write(line)
                handle.flush()
        except Exception as exc:
            print(f"[RuntimeSupervisor] failed to write lifecycle event {event}: {exc}", file=sys.stderr)

    def thread_snapshot(self) -> list[dict[str, Any]]:
        return [
            {"name": thread.name, "ident": thread.ident, "daemon": thread.daemon, "alive": thread.is_alive()}
            for thread in threading.enumerate()
        ]

    def _watchdog_loop(self) -> None:
        if self._stop.wait(self.startup_grace_seconds):
            return
        while not self._stop.is_set():
            self._probe_listener()
            self._probe_critical_threads()
            self._stop.wait(self.probe_interval_seconds)

    def _probe_listener(self) -> None:
        with self._lock:
            host, port = self._host, self._port
        if not host or port <= 0:
            return
        healthy = False
        error = ""
        try:
            with socket.create_connection((host, port), timeout=2.0):
                healthy = True
        except OSError as exc:
            error = f"{type(exc).__name__}: {exc}"
        with self._lock:
            previous = self._listener_state
            self._listener_state = healthy
        if previous is healthy:
            return
        self.record(
            "listener_state_changed",
            level="info" if healthy else "error",
            healthy=healthy,
            host=host,
            port=port,
            error=error,
            threads=self.thread_snapshot() if not healthy else [],
        )

    def _probe_critical_threads(self) -> None:
        with self._lock:
            registered = list(self._critical_threads.items())
        for name, (thread, expected_running) in registered:
            expected = True
            if expected_running is not None:
                try:
                    expected = bool(expected_running())
                except Exception as exc:
                    self.record(
                        "critical_thread_expectation_failed",
                        level="error",
                        critical_thread=name,
                        exception=f"{type(exc).__name__}: {exc}",
                    )
            if not expected or thread.is_alive():
                continue
            with self._lock:
                if name in self._reported_dead_threads:
                    continue
                self._reported_dead_threads.add(name)
            self.record(
                "critical_thread_dead",
                level="error",
                critical_thread=name,
                registered_ident=thread.ident,
                threads=self.thread_snapshot(),
            )

    def _thread_excepthook(self, args: threading.ExceptHookArgs) -> None:
        self.record(
            "thread_uncaught_exception",
            level="error",
            failed_thread_name=args.thread.name if args.thread is not None else "",
            failed_thread_ident=args.thread.ident if args.thread is not None else None,
            exception_type=args.exc_type.__name__ if args.exc_type is not None else "",
            exception=str(args.exc_value or ""),
            traceback="".join(traceback.format_exception(args.exc_type, args.exc_value, args.exc_traceback)),
            threads=self.thread_snapshot(),
        )
        self._previous_thread_excepthook(args)


runtime_supervisor = RuntimeSupervisor()


__all__ = ["LIFECYCLE_LOG_FILENAME", "RuntimeSupervisor", "runtime_supervisor"]
