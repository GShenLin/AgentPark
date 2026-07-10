import os
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import Response

from .companion_mcp import build_companion_mcp
from .core import BackendCore
from .cors_policy import configured_cors_allow_origins
from .cors_policy import cors_allow_origin_regex
from .cors_policy import is_allowed_private_network_origin
from .cors_policy import private_network_access_enabled
from .node_desktop_pet_launcher import terminate_registered_desktop_pet_processes
from .runtime_paths import _get_resource_root, _get_runtime_root
from .route_registry import ApiRouteRegistry


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
            CORSMiddleware,
            allow_origins=configured_cors_allow_origins(),
            allow_origin_regex=cors_allow_origin_regex(),
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
        self.app.middleware("http")(self._private_network_access_headers)
        self._desktop_pet_restore_timer = None

    async def _private_network_access_headers(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        origin = str(request.headers.get("origin") or "").strip()
        if (
            private_network_access_enabled()
            and request.headers.get("access-control-request-private-network") == "true"
            and is_allowed_private_network_origin(origin)
        ):
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response

    def register_routes(self) -> None:
        ApiRouteRegistry.register(self.app, self.core)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI):
        if self.companion_mcp is None:
            self._startup_services()
            try:
                yield
            finally:
                self._shutdown_services()
            return

        async with self.companion_mcp.session_manager.run():
            self._startup_services()
            try:
                yield
            finally:
                self._shutdown_services()

    def _startup_services(self) -> None:
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
            self.core.graph_runtime._ensure_timer_trigger_scheduler()
            channels = self.core.channel_service.start_autostart_receivers()
            if isinstance(channels, dict):
                print(f"[ChannelService] autostart receivers={int(channels.get('started', 0))}")
            if str(os.environ.get("AGENTPARK_RESTORE_DESKTOP_PETS") or "").strip() == "1":
                self._schedule_desktop_pet_restore()
            else:
                result = self.core.node_desktop_views.mark_all_desktop_pets_hidden()
                if isinstance(result, dict) and int(result.get("updated", 0)) > 0:
                    print(f"[DesktopPet] skipped restore; hidden stale views={int(result.get('updated', 0))}")
        except Exception as e:
            print(f"[GraphRuntime] startup failed: {e}")

    def _schedule_desktop_pet_restore(self) -> None:
        if self._desktop_pet_restore_timer is not None:
            return

        def restore() -> None:
            try:
                result = self.core.node_desktop_views.restore_visible_desktop_pets()
                failed = result.get("failed") if isinstance(result, dict) else []
                print(
                    "[DesktopPet] restore "
                    f"requested={int(result.get('requested', 0))} "
                    f"restored={int(result.get('restored', 0))} "
                    f"failed={len(failed) if isinstance(failed, list) else 0}"
                )
                if failed:
                    print(f"[DesktopPet] restore failures={failed}")
            except Exception as e:
                print(f"[DesktopPet] restore failed: {e}")

        timer = threading.Timer(1.0, restore)
        timer.daemon = True
        self._desktop_pet_restore_timer = timer
        timer.start()

    def _shutdown_services(self) -> None:
        timer = self._desktop_pet_restore_timer
        if timer is not None:
            timer.cancel()
            self._desktop_pet_restore_timer = None
        try:
            result = terminate_registered_desktop_pet_processes()
            if isinstance(result, dict) and int(result.get("requested") or 0) > 0:
                failed = result.get("failed") if isinstance(result.get("failed"), list) else []
                print(
                    "[DesktopPet] shutdown "
                    f"requested={int(result.get('requested') or 0)} "
                    f"terminated={len(result.get('terminated') or [])} "
                    f"failed={len(failed)}"
                )
                if failed:
                    print(f"[DesktopPet] shutdown failures={failed}")
        except Exception as e:
            print(f"[DesktopPet] shutdown failed: {e}")
        try:
            self.core.graph_runtime._stop_timer_trigger_scheduler()
        except Exception:
            pass
        try:
            self.core.channel_service.stop_all()
        except Exception:
            pass

    def build(self) -> FastAPI:
        self.register_routes()
        self.companion_mcp = build_companion_mcp(self.core)
        self.companion_mcp_app = self.companion_mcp.streamable_http_app()
        self.app.mount("/mcp", self.companion_mcp_app, name="companion-mcp")

        base_dir = _get_runtime_root()
        memories_dir = os.path.join(base_dir, "memories")
        os.makedirs(memories_dir, exist_ok=True)

        self.app.mount("/memories", StaticFiles(directory=memories_dir), name="memories")

        dist_candidates = [
            os.path.join(_get_resource_root(), "webui", "dist"),
            os.path.join(_get_runtime_root(), "webui", "dist"),
        ]
        dist_dir = next((p for p in dist_candidates if os.path.isdir(p)), "")
        if dist_dir:
            self.app.mount("/", StaticFiles(directory=dist_dir, html=True), name="webui")

        return self.app
