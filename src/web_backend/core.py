import multiprocessing
import threading
import uuid

from .agent_domain import AgentDomain
from .core_graph_api import GraphApiDomain
from .core_graph_runtime import GraphRuntimeDomain
from .core_node_ops import NodeOpsDomain
from .core_system_api import SystemApiDomain
from .graph_event_stream import GraphEventStreamStore
from .mobile_api import MobileApiDomain
from .node_desktop_view import NodeDesktopViewDomain
from .node_cancellation import NodeCancellationRegistry
from .node_live_output import NodeLiveOutputStore
from .node_config_service import RUNTIME_STATE_FIELDS
from .pet_avatar import PetAvatarDomain
from .profile_api import ProfileApi
from .remote_api import RemoteApiDomain
from .settings_api import SettingsApiDomain
from .user_interaction_api import UserInteractionApiDomain
from src.channels.service import ChannelService
from src.provider_limit_jobs import ProviderLimitJobStore


class BackendCore:
    def __init__(self, tool_names: list[str] | None = None) -> None:
        self.tool_names = tool_names
        self.runtime_owner_id = uuid.uuid4().hex
        self.node_runs = {}
        self.mp_ctx = multiprocessing.get_context("spawn")
        self.default_graph_id = "default"
        self.graph_runners: dict[str, dict] = {}
        self.graph_runners_lock = threading.Lock()
        self.timer_scheduler_thread: threading.Thread | None = None
        self.timer_scheduler_stop: threading.Event | None = None
        self.timer_scheduler_lock = threading.Lock()
        self.timer_trigger_last_fired: dict[str, str] = {}
        self.node_cancellations = NodeCancellationRegistry()
        self.node_live_outputs = NodeLiveOutputStore()
        self.graph_events = GraphEventStreamStore()
        self.provider_limit_jobs = ProviderLimitJobStore()
        self.reserved_node_fields = {
            "node_id",
            "type_id",
            "name",
            "graph_id",
            "ui",
            "schema",
            "input_num",
            "output_num",
            *RUNTIME_STATE_FIELDS,
        }

        self.graph_runtime = GraphRuntimeDomain(self)
        self.channel_service = ChannelService(self)
        self.agent_domain = AgentDomain(self, self.graph_runtime)
        self.node_ops = NodeOpsDomain(self, self.graph_runtime)
        self.graph_api = GraphApiDomain(self, self.graph_runtime)
        self.profile_api = ProfileApi(self)
        self.mobile_api = MobileApiDomain(self, self.graph_runtime)
        self.node_desktop_views = NodeDesktopViewDomain(self, self.graph_runtime)
        self.pet_avatars = PetAvatarDomain(self)
        self.remote_api = RemoteApiDomain(self)
        self.settings_api = SettingsApiDomain(self)
        self.user_interaction_api = UserInteractionApiDomain(self)
        self.system_api = SystemApiDomain(self, self.agent_domain)


__all__ = ["BackendCore"]
