from .paste_agent_settings import PasteAgentSettings
from .prompt_library import PromptLibrary
from .domain_base import DomainBase
from .shared import ConfigLoader, HTTPException


class AgentDomain(DomainBase):
    def __init__(self, core, graph_runtime):
        super().__init__(core, graph_runtime)
        object.__setattr__(self, "_service_targets_cache", None)

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            cached = (
                PasteAgentSettings(self),
                PromptLibrary(self),
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    def _list_provider_support(self):
        providers = ConfigLoader().get_all_providers()
        items = []
        if isinstance(providers, dict):
            for provider_id, config in providers.items():
                if not isinstance(provider_id, str):
                    provider_id = str(provider_id)
                modes = []
                if isinstance(config, dict):
                    raw_modes = config.get("supportmode")
                    if isinstance(raw_modes, (list, tuple, set)):
                        for mode in raw_modes:
                            if mode is None:
                                continue
                            value = str(mode).strip().lower()
                            if value:
                                modes.append(value)
                if not modes:
                    modes = ["chat"]
                items.append({"id": provider_id, "supportmode": modes})
        items.sort(key=lambda x: x.get("id", ""))
        return items

    def get_subagent_memory(self, task_id: int, name: str, max_chars: int = 20000):
        raise HTTPException(status_code=404, detail="subagent is disabled")

    def stop_subagent(self, task_id: int, name: str):
        raise HTTPException(status_code=404, detail="subagent is disabled")


__all__ = ["AgentDomain"]
