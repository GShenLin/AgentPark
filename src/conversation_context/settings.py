from dataclasses import dataclass, fields


@dataclass(frozen=True)
class ConversationSettings:
    input_tokens: int = 24000
    retain_tokens: int = 6000
    summary_tokens: int = 2000
    profile_id: str = "DouBao"

    @classmethod
    def from_config(cls, config: dict) -> "ConversationSettings":
        raw = config.get("conversationContext", {})
        if not isinstance(raw, dict):
            raise ValueError("conversationContext must be an object")
        defaults = cls()
        unknown = set(raw) - {field.name for field in fields(cls)}
        if unknown:
            raise ValueError(f"unknown conversationContext settings: {sorted(unknown)}")
        for key, value in raw.items():
            if type(value) is not type(getattr(defaults, key)):
                raise ValueError(f"invalid type for conversationContext.{key}")
            if isinstance(value, int) and value < 1:
                raise ValueError(f"conversationContext.{key} must be positive")
        result = cls(**raw)
        if not result.profile_id.strip():
            raise ValueError("conversationContext.profile_id must be non-empty")
        if result.input_tokens < 4096:
            raise ValueError("conversationContext.input_tokens must be at least 4096")
        if result.retain_tokens + result.summary_tokens + 1024 >= result.input_tokens:
            raise ValueError("conversationContext must leave over 1024 tokens beyond retained history and summary")
        return result
