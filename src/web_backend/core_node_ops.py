from .domain_base import DomainBase
from .node_async_runs import NodeAsyncRuns
from .node_catalog import NodeCatalog
from .codex_session_runtime import CodexSessionRuntime
from .node_instance_deletion import NodeInstanceDeletion
from .node_instance_files import NodeInstanceFiles
from .node_instance_config_query import NodeInstanceConfigQuery
from .node_instance_queue import NodeInstanceQueue
from .node_instance_registry import NodeInstanceRegistry
from .node_instance_runtime import NodeInstanceRuntime
from .node_visibility import NodeVisibilityService
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
                CodexSessionRuntime(self),
                NodeInstanceDeletion(self),
                NodeInstanceFiles(self),
                NodeInstanceConfigQuery(self),
                NodeInstanceRegistry(self),
                NodeInstanceRuntime(self),
                NodeInstanceQueue(self),
                NodeAsyncRuns(self),
                NodeVisibilityService(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached


__all__ = ["NodeOpsDomain"]
