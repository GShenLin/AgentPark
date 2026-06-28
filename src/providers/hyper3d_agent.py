from src.base_agent import BaseAgent
from src.providers.hyper3d_rodin_runtime import Hyper3DRodinRuntime
from src.providers.hyper3d_texture_runtime import Hyper3DTextureRuntime
from src.service_host import ServiceHost


class Hyper3DAgent(ServiceHost, BaseAgent):
    def __init__(self, provider_id="hyper3d", memory_file_path=None, system_prompt=None, internal_memory_enabled=True):
        super().__init__(
            provider_id,
            memory_file_path=memory_file_path,
            system_prompt=system_prompt,
            internal_memory_enabled=internal_memory_enabled,
        )
        self.config = self._read_provider_config_from_file()
        self.system_prompt = system_prompt
        self._service_targets_cache = None

    def _iter_service_targets(self) -> tuple[object, ...]:
        cached = self._service_targets_cache
        if cached is None:
            cached = (Hyper3DRodinRuntime(self), Hyper3DTextureRuntime(self))
            self._service_targets_cache = cached
        return cached

    def Send(self, *args, **kwargs):
        raise ValueError("Hyper3D provider supports explicit generation methods only.")
