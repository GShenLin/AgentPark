from fastapi import FastAPI

from .facade import WebBackendFacade
from .runtime_paths import _get_resource_root, _get_runtime_root


def create_app(tool_names: list[str] | None = None) -> FastAPI:
    return WebBackendFacade(tool_names=tool_names).build()


app = create_app()


__all__ = [
    "WebBackendFacade",
    "create_app",
    "app",
    "_get_runtime_root",
    "_get_resource_root",
]
