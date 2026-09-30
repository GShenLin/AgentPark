"""Load agent machinery only when used; curl is also used during authentication."""
from importlib import import_module


def __getattr__(name):
    modules = {"create_agent": "registry", "AgentConfig": "agent_config",
               "AgentSendContext": "agent_config", "send_agent": "agent_invocation"}
    if name not in modules:
        raise AttributeError(name)
    value = getattr(import_module(f"{__name__}.{modules[name]}"), name)
    globals()[name] = value
    return value


__all__ = ["AgentConfig", "AgentSendContext", "create_agent", "send_agent"]
