import multiprocessing
import threading

from .agent_domain import AgentDomain
from .core_graph_api import GraphApiDomain
from .core_graph_runtime import GraphRuntimeDomain
from .core_node_ops import NodeOpsDomain
from .core_system_api import SystemApiDomain
from .mobile_api import MobileApiDomain


class BackendCore:
    def __init__(self, tool_names: list[str] | None = None) -> None:
        self.tool_names = tool_names
        self.node_runs = {}
        self.mp_ctx = multiprocessing.get_context("spawn")
        self.default_graph_id = "default"
        self.graph_runners: dict[str, dict] = {}
        self.graph_runners_lock = threading.Lock()
        self.timer_scheduler_thread: threading.Thread | None = None
        self.timer_scheduler_stop: threading.Event | None = None
        self.timer_scheduler_lock = threading.Lock()
        self.timer_trigger_last_fired: dict[str, str] = {}
        self.reserved_node_fields = {
            "node_id",
            "type_id",
            "name",
            "graph_id",
            "state",
            "ui",
            "pending",
            "pending_count",
            "inflight",
            "schema",
            "last_message",
            "last_runtime_event",
            "runtime_events",
            "runtime_tool_calls",
            "last_run_at",
            "input_num",
            "output_num",
        }

        self.graph_runtime = GraphRuntimeDomain(self)
        self.agent_domain = AgentDomain(self, self.graph_runtime)
        self.node_ops = NodeOpsDomain(self, self.graph_runtime)
        self.graph_api = GraphApiDomain(self, self.graph_runtime)
        self.mobile_api = MobileApiDomain(self, self.graph_runtime)
        self.system_api = SystemApiDomain(self, self.agent_domain)


__all__ = ["BackendCore"]
