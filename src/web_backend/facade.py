import asyncio
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from nodes.agent_plugin_api_loader import register_installed_plugin_apis
from nodes.agent_plugin_loader import default_plugin_root
from src.public_gateway.routes import register_public_gateway_routes
from src.runtime_supervision import runtime_supervisor

from .companion_mcp import build_companion_mcp
from .core import BackendCore
from .network_diagnostics import NetworkDiagnosticsMiddleware
from .node_open_diagnostics import NodeOpenDiagnosticsMiddleware
from .memory_static_files import VisibilityAwareMemoriesStaticFiles
from . import runtime_paths
from .private_network_cors import PrivateNetworkCORSMiddleware
from .route_registry import ApiRouteRegistry
from .peer_api import register_peer_routes
from .knowledge_api import register_knowledge_routes
from .group_api import register_group_routes
from .node_sync.routes import register_node_sync_routes


class WebBackendFacade:
    def __init__(self, tool_names: list[str] | None = None) -> None:
        self.core = BackendCore(tool_names=tool_names)
        self.companion_mcp = None
        self.companion_mcp_app = None
        self.app = FastAPI(
            title="AgentPark Mission2 Web",
            lifespan=self._lifespan,
        )
        self.app.add_middleware(
            PrivateNetworkCORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
            allow_private_network=True,
        )
        self.app.add_middleware(NetworkDiagnosticsMiddleware)
        self.app.add_middleware(NodeOpenDiagnosticsMiddleware)

    def register_routes(self) -> None:
        ApiRouteRegistry.register(self.app, self.core)
        register_group_routes(self.app, self.core)
        self.node_sync_jobs = register_node_sync_routes(self.app, self.core)
        register_knowledge_routes(self.app, self.core.knowledge_service)
        register_peer_routes(self.app, self.core)
        register_public_gateway_routes(self.app, self.core.public_gateway_api.service)
        register_installed_plugin_apis(
            self.app,
            plugin_root=default_plugin_root(),
            runtime_root=runtime_paths._get_runtime_root(),
            resource_root=runtime_paths._get_resource_root(),
            core=self.core,
        )

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI):
        runtime_supervisor.attach_asyncio_loop(asyncio.get_running_loop())
        runtime_supervisor.record("application_lifespan_starting")
        if self.companion_mcp is None:
            self._startup_services()
            runtime_supervisor.record("application_lifespan_ready")
            try:
                await self.core.peer_api.start()
                yield
            finally:
                runtime_supervisor.record("application_lifespan_stopping")
                await self.core.peer_api.close()
                self._shutdown_services()
                runtime_supervisor.record("application_lifespan_stopped")
            return

        async with self.companion_mcp.session_manager.run():
            self._startup_services()
            runtime_supervisor.record("application_lifespan_ready")
            try:
                await self.core.peer_api.start()
                yield
            finally:
                runtime_supervisor.record("application_lifespan_stopping")
                await self.core.peer_api.close()
                self._shutdown_services()
                runtime_supervisor.record("application_lifespan_stopped")

    def _startup_services(self) -> None:
        self.core.knowledge_service.start()
        self.core.group_delivery.start()
        try:
            recovery = self.core.graph_runtime._recover_node_runtime_state_on_startup()
            if isinstance(recovery, dict):
                print(
                    "[GraphRuntime] startup recovery "
                    f"graphs_woken={int(recovery.get('graphs_woken', 0))} "
                    f"nodes_reset_to_idle={int(recovery.get('nodes_reset_to_idle', 0))} "
                    f"inflight_requeued={int(recovery.get('inflight_requeued', 0))}"
                )
            events = self.core.runtime_events.startup()
            if isinstance(events, dict):
                companion = events.get("companion_recovery") if isinstance(events.get("companion_recovery"), dict) else {}
                print(
                    "[RuntimeEvents] startup "
                    f"companion_inbox_cleared={int(companion.get('companion_inbox_cleared', 0))} "
                    f"temporary_receivers_found={int(companion.get('temporary_receivers_found', 0))} "
                    f"temporary_receivers_cleaned={int(companion.get('temporary_receivers_cleaned', 0))}"
                )
            self._recover_restart_checkpoints()
            self.core.graph_runtime._ensure_timer_trigger_scheduler()
            channels = self.core.channel_service.start_autostart_receivers()
            if isinstance(channels, dict):
                print(f"[ChannelService] autostart receivers={int(channels.get('started', 0))}")
        except Exception as e:
            print(f"[GraphRuntime] startup failed: {e}")

    def _recover_restart_checkpoints(self) -> None:
        try:
            result = self.core.restart_recovery.recover_pending_nodes()
            failures = result.get("failures") if isinstance(result, dict) else []
            print(
                "[RestartRecovery] startup "
                f"recovered={int(result.get('recovered', 0))} "
                f"claimed={int(result.get('claimed', 0))} "
                f"completed_cleaned={int(result.get('completed_cleaned', 0))} "
                f"failed={len(failures) if isinstance(failures, list) else 0}"
            )
            if failures:
                print(f"[RestartRecovery] failures={failures}")
        except Exception as e:
            print(f"[RestartRecovery] startup failed; checkpoint retained: {e}")

    def _shutdown_services(self) -> None:
        self.node_sync_jobs.cloud.close()
        self.core.group_delivery.close()
        self.core.knowledge_service.close()
        try:
            self.core.graph_runtime._stop_timer_trigger_scheduler()
        except Exception:
            pass
        try:
            self.core.channel_service.stop_all()
        except Exception:
            pass
        try:
            self.core.remote_workspace_api.close()
        except Exception:
            pass

    def build(self) -> FastAPI:
        self.register_routes()
        self.companion_mcp = build_companion_mcp(self.core)
        self.companion_mcp_app = self.companion_mcp.streamable_http_app()
        self.app.mount("/mcp", self.companion_mcp_app, name="companion-mcp")

        memories_dir = runtime_paths._get_graphs_dir()
        os.makedirs(memories_dir, exist_ok=True)

        self.app.mount(
            "/memories",
            VisibilityAwareMemoriesStaticFiles(directory=memories_dir, core=self.core),
            name="memories",
        )

        dist_candidates = [
            os.path.join(runtime_paths._get_resource_root(), "webui", "dist"),
            os.path.join(runtime_paths._get_runtime_root(), "webui", "dist"),
        ]
        dist_dir = next((p for p in dist_candidates if os.path.isdir(p)), "")
        if dist_dir:
            self.app.mount("/", StaticFiles(directory=dist_dir, html=True), name="webui")

        return self.app
