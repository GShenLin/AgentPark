from __future__ import annotations

"""Map generation options to the Ark Responses contract."""

from typing import Any


def normalize_generation_options(request: dict[str, Any]) -> None:
    # Ark reasoning exposes effort only. Codex's context selector does not
    # control the input history: all supplied turns remain in request.input.
    # Summary and verbosity are OpenAI generation hints without Ark equivalents.
    # Remove only these known extensions; preserve format/schema constraints and
    # let upstream report any other unsupported options instead of masking them.
    for field, extensions in (
        ("reasoning", ("context", "summary")),
        ("text", ("verbosity",)),
    ):
        value = request.get(field)
        if not isinstance(value, dict):
            continue
        for extension in extensions:
            value.pop(extension, None)
        if not value:
            request.pop(field)
