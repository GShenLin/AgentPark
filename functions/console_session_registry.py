"""Session ownership is an Agent run, never a PID supplied by the model."""

from contextlib import contextmanager
import threading

from functions.console_session_process import ConsoleSession
from src.providers.agent_runtime_context import get_agent_runtime_context


_BIND_LOCK = threading.Lock()


class ConsoleSessionRegistry:
    def __init__(self):
        self.lock = threading.RLock()
        self.sessions = {}
        self.closed = False

    def start(self, **kwargs):
        with self.lock:
            if self.closed:
                raise ValueError("Agent run has ended; its console sessions are closed")
            if len(self.sessions) >= 128 or sum(not s.done.is_set() for s in self.sessions.values()) >= 8:
                raise ValueError("Console session limit reached (8 running, 128 retained per Agent run)")
            session = ConsoleSession(**kwargs)
            self.sessions[session.session_id] = session
            return session

    def get(self, session_id):
        with self.lock:
            if not isinstance(session_id, str) or not session_id:
                raise ValueError("session_id must be a non-empty string")
            if self.closed or session_id not in self.sessions:
                raise ValueError("Unknown console session for this Agent run")
            return self.sessions[session_id]

    def close(self):
        with self.lock:
            self.closed = True
            sessions = list(self.sessions.values())
            for session in sessions:
                session.stop_requested.set()
        errors = []
        for session in sessions:
            try:
                session.close()
            except Exception as exc:
                errors.append(str(exc))
        if errors:
            raise RuntimeError("Console session cleanup failed: " + "; ".join(errors))


def registry_for(agent):
    if agent is None:
        raise ValueError("Process sessions require an owning Agent run")
    if get_agent_runtime_context(agent).remote_enabled:
        raise ValueError("Process sessions currently require local execution; remote sessions are not supported")
    with _BIND_LOCK:
        registry = getattr(agent, "_console_session_registry", None)
        if registry is None:
            registry = ConsoleSessionRegistry()
            agent._console_session_registry = registry
        return registry


@contextmanager
def console_session_scope(agent):
    with _BIND_LOCK:
        previous = getattr(agent, "_console_session_registry", None)
        if previous is not None and previous.closed:
            agent._console_session_registry = ConsoleSessionRegistry()
    try:
        yield
    finally:
        with _BIND_LOCK:
            registry = getattr(agent, "_console_session_registry", None)
        if registry is not None:
            registry.close()
