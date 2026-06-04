import inspect


class ServiceHost:
    def _iter_service_targets(self) -> tuple[object, ...]:
        return ()

    def _iter_forward_targets(self) -> tuple[object, ...]:
        return tuple(target for target in self._iter_service_targets() if target is not None)

    def __getattr__(self, name: str):
        for target in self._iter_forward_targets():
            try:
                inspect.getattr_static(target, name)
            except AttributeError:
                continue
            return getattr(target, name)
        raise AttributeError(f"{type(self).__name__!s} has no attribute {name!r}")


class HostBoundService:
    def __init__(self, host: object) -> None:
        object.__setattr__(self, "_host", host)

    def __getattribute__(self, name: str):
        if name.startswith("__") or name in {"_host", "host", "core"}:
            return object.__getattribute__(self, name)
        host = object.__getattribute__(self, "_host")
        try:
            return object.__getattribute__(host, name)
        except AttributeError:
            return object.__getattribute__(self, name)

    @property
    def host(self) -> object:
        return object.__getattribute__(self, "_host")

    @property
    def core(self) -> object:
        host = self.host
        if hasattr(host, "core"):
            return getattr(host, "core")
        return getattr(host, "_core")

    def __getattr__(self, name: str):
        return getattr(self.host, name)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        setattr(self.host, name, value)


__all__ = ["HostBoundService", "ServiceHost"]
