from .service_host import ServiceHost


class DomainBase(ServiceHost):
    def __init__(self, core: object, *dependencies: object) -> None:
        object.__setattr__(self, "_core", core)
        object.__setattr__(self, "_dependencies", tuple(dep for dep in dependencies if dep is not None))

    @property
    def core(self) -> object:
        return object.__getattribute__(self, "_core")

    def _iter_forward_targets(self) -> tuple[object, ...]:
        dependencies = object.__getattribute__(self, "_dependencies")
        core = object.__getattribute__(self, "_core")
        return super()._iter_forward_targets() + tuple(dependencies) + (core,)

    def __setattr__(self, name: str, value) -> None:
        if name.startswith("_"):
            object.__setattr__(self, name, value)
            return
        core = object.__getattribute__(self, "_core")
        setattr(core, name, value)


__all__ = ["DomainBase"]
