"""Run-scoped execution ownership and switching barriers shared by all tools."""
from contextlib import contextmanager
from dataclasses import dataclass, field
import threading


CONTROL_TOOLS = frozenset({
    "list_execution_devices", "inspect_execution_workspace", "switch_execution_device",
})
_BIND_LOCK = threading.Lock()


@dataclass
class ExecutionDeviceState:
    lock: object = field(default_factory=threading.RLock)
    active_operations: int = 0
    switching: bool = False
    revision: int = 0


def device_state(agent: object) -> ExecutionDeviceState:
    if agent is None:
        raise ValueError("Device operations require an owning Agent run.")
    with _BIND_LOCK:
        state = getattr(agent, "_execution_device_state", None)
        if state is None:
            state = ExecutionDeviceState()
            agent._execution_device_state = state
        return state


@contextmanager
def execution_operation(agent: object, tool_name: str):
    state = getattr(agent, "_execution_device_state", None)
    if state is None or tool_name in CONTROL_TOOLS:
        yield
        return
    with state.lock:
        if state.switching:
            raise RuntimeError("Execution device switch is in progress; wait for its result before running tools.")
        state.active_operations += 1
    try:
        yield
    finally:
        with state.lock:
            state.active_operations -= 1


@contextmanager
def switching_device(agent: object, expected_revision: int):
    state = device_state(agent)
    with state.lock:
        if type(expected_revision) is not int or expected_revision != state.revision:
            raise ValueError("Execution revision changed; list_execution_devices before switching again.")
        if state.switching or state.active_operations:
            raise RuntimeError("Tools are still running; wait for them to finish before switching devices.")
        registry = getattr(agent, "_console_session_registry", None)
        if registry is not None:
            with registry.lock:
                if any(not session.done.is_set() for session in registry.sessions.values()):
                    raise RuntimeError("A console session is still running; finish or stop it before switching devices.")
        state.switching = True
    try:
        yield state
    finally:
        with state.lock:
            state.switching = False
