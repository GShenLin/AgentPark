from fastapi import FastAPI

from . import runtime_paths


def create_app(tool_names: list[str] | None = None) -> FastAPI:
    from .facade import WebBackendFacade

    return WebBackendFacade(tool_names=tool_names).build()

_get_runtime_root = runtime_paths._get_runtime_root
_get_resource_root = runtime_paths._get_resource_root


def __getattr__(name: str):
    if name == "WebBackendFacade":
        from .facade import WebBackendFacade

        return WebBackendFacade
    raise AttributeError(name)


__all__ = [
    "WebBackendFacade",
    "create_app",
    "_get_runtime_root",
    "_get_resource_root",
]
