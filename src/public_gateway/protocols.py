"""Public protocol capabilities, independent of conversational wire adapters."""
from typing import Any

from src.cli_provider_runtime.provider_adapter import provider_protocol


CHAT_PROTOCOLS = ("responses", "chat_completions", "messages")
IMAGE_PROTOCOLS = ("images_generations", "images_edits")
PROTOCOLS = (*CHAT_PROTOCOLS, *IMAGE_PROTOCOLS)


def supported_protocols(config: dict[str, Any]) -> tuple[str, ...]:
    modes = config.get("supportmode", [])
    protocols: tuple[str, ...] = ()
    if any(mode in modes for mode in ("chat", "imagechat")):
        provider_protocol(config)
        protocols = CHAT_PROTOCOLS
    # Other image providers have different wire contracts; do not advertise
    # Images API support merely because they can generate images.
    if "image_generation" in modes and config.get("type") == "openai":
        protocols += IMAGE_PROTOCOLS
    return protocols
