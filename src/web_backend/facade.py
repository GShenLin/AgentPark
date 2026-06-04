import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .core import BackendCore
from .runtime_paths import _get_resource_root, _get_runtime_root
from .route_registry import ApiRouteRegistry


class WebBackendFacade:
    def __init__(self, tool_names: list[str] | None = None) -> None:
        self.core = BackendCore(tool_names=tool_names)
        self.app = FastAPI(
            title="AITools Mission2 Web",
            lifespan=self._lifespan,
        )
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=["*"],
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    def register_routes(self) -> None:
        ApiRouteRegistry.register(self.app, self.core)

    @asynccontextmanager
    async def _lifespan(self, _app: FastAPI):
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
            self.core.graph_runtime._ensure_timer_trigger_scheduler()
        except Exception as e:
            print(f"[GraphRuntime] startup failed: {e}")

    def _shutdown_services(self) -> None:
        try:
            self.core.graph_runtime._stop_timer_trigger_scheduler()
        except Exception:
            pass

    def build(self) -> FastAPI:
        self.register_routes()

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
