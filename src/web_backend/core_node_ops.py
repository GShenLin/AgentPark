from .domain_base import DomainBase
from .node_async_runs import NodeAsyncRuns
from .node_catalog import NodeCatalog
from .node_instance_deletion import NodeInstanceDeletion
from .node_instance_queue import NodeInstanceQueue
from .node_instance_registry import NodeInstanceRegistry
from .node_instance_runtime import NodeInstanceRuntime
from .shared import *


class NodeOpsDomain(DomainBase):
    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                NodeCatalog(self),
                NodeInstanceDeletion(self),
                NodeInstanceRegistry(self),
                NodeInstanceRuntime(self),
                NodeInstanceQueue(self),
                NodeAsyncRuns(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached


__all__ = ["NodeOpsDomain"]
