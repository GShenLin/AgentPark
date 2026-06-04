from .domain_base import DomainBase
from .graph_message_dispatch import GraphMessageDispatch
from .graph_node_execution import GraphNodeExecution
from .graph_node_store import GraphNodeStore
from .graph_runner_runtime import GraphRunnerRuntime
from .graph_runtime_registry import GraphRuntimeRegistry
from .graph_timer_scheduler import GraphTimerScheduler
from .shared import *


class GraphRuntimeDomain(DomainBase):
    def __init__(self, core):
        super().__init__(core)
        object.__setattr__(self, "_service_targets_cache", None)

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                GraphRuntimeRegistry(self),
                GraphTimerScheduler(self),
                GraphNodeStore(self),
                GraphMessageDispatch(self),
                GraphRunnerRuntime(self),
                GraphNodeExecution(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached


__all__ = ["GraphRuntimeDomain"]
