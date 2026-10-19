"""Expose the live node run's execution context without persisting a stale target."""
from contextlib import contextmanager
import os
import threading

from src.providers.agent_runtime_context import get_agent_runtime_context
from .device_state import device_state

_lock = threading.RLock()
_agents: dict[str, object] = {}


def _key(directory: str):
    return os.path.normcase(os.path.abspath(directory))


@contextmanager
def active_node_execution(agent):
    context = get_agent_runtime_context(agent)
    if not context.node_directory:
        raise ValueError('Active node execution requires its owning node directory.')
    key = _key(context.node_directory)
    with _lock:
        if key in _agents:
            raise RuntimeError('Another execution already owns this node.')
        _agents[key] = agent
    try:
        yield
    finally:
        with _lock:
            if _agents.get(key) is agent:
                del _agents[key]


def active_execution_context(directory: str):
    with _lock:
        agent = _agents.get(_key(directory))
        if agent is None:
            return None
        state = device_state(agent)
        with state.lock:
            if state.switching:
                raise RuntimeError('节点正在切换执行设备，请稍后重新开启共享。')
            return get_agent_runtime_context(agent)
