from .types import CapabilityDescriptor, CapabilityRef

__all__ = [
    "CapabilityDescriptor",
    "CapabilityRef",
    "CapabilityRegistry",
    "discover_capabilities",
]


def __getattr__(name):
    if name in {"CapabilityRegistry", "discover_capabilities"}:
        from .registry import CapabilityRegistry, discover_capabilities

        return {"CapabilityRegistry": CapabilityRegistry, "discover_capabilities": discover_capabilities}[name]
    raise AttributeError(name)
