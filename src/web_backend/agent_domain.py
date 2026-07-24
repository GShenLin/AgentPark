from .input_bundle_library import InputBundleLibrary
from .paste_agent_settings import PasteAgentSettings
from .prompt_library import PromptLibrary
from .domain_base import DomainBase
from .shared import HTTPException


class AgentDomain(DomainBase):
    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                PasteAgentSettings(self),
                PromptLibrary(self),
                InputBundleLibrary(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    def get_subagent_memory(self, task_id: int, name: str, max_chars: int = 20000):
        raise HTTPException(status_code=404, detail="subagent is disabled")

    def stop_subagent(self, task_id: int, name: str):
        raise HTTPException(status_code=404, detail="subagent is disabled")


__all__ = ["AgentDomain"]
