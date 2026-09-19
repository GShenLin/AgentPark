from dataclasses import dataclass, fields


@dataclass(frozen=True)
class MemorySettings:
    enabled: bool = True
    extract_provider: str = ""
    consolidation_provider: str = ""
    min_idle_seconds: int = 3600
    max_age_days: int = 30
    max_unused_days: int = 30
    max_extractions: int = 8
    max_selected: int = 64
    input_bytes: int = 180000
    consolidation_bytes: int = 240000
    lease_seconds: int = 180
    retry_seconds: int = 3600

    @classmethod
    def from_config(cls, config: dict) -> "MemorySettings":
        raw = config.get("longTermMemory", {})
        if not isinstance(raw, dict):
            raise ValueError("longTermMemory must be an object")
        defaults = cls()
        known = {field.name for field in fields(cls)}
        if set(raw) - known:
            raise ValueError(f"unknown longTermMemory settings: {sorted(set(raw) - known)}")
        for key, value in raw.items():
            if type(value) is not type(getattr(defaults, key)):
                raise ValueError(f"invalid type for longTermMemory.{key}")
            if isinstance(value, int) and not isinstance(value, bool):
                minimum = 0 if key == "min_idle_seconds" else 1
                if value < minimum:
                    raise ValueError(f"longTermMemory.{key} must be >= {minimum}")
        return cls(**raw)
