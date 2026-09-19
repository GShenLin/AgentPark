from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


class ComputerUseError(ValueError):
    """An action cannot safely use the supplied desktop observation."""


@dataclass
class Observation:
    owner: str
    window: dict
    rect: tuple[int, int, int, int]
    elements: list[dict]
    focus: list[int] | None
    created: float
    generation: int
    has_image: bool


class DesktopBackend(Protocol):
    """OS operations; the service owns observation lifetime and serialization."""

    def list_windows(self) -> list[dict]: ...
    def list_apps(self) -> list[dict]: ...
    def resolve(self, window: dict) -> dict: ...
    def rectangle(self, window: dict) -> tuple[int, int, int, int]: ...
    def observe(self, window: dict, include_text: bool, max_elements: int, cancel: Any) -> dict: ...
    def capture(self, window: dict, cancel: Any): ...
    def activate(self, window: dict) -> None: ...
    def launch(self, app: str) -> None: ...
    def act(self, action: str, window: dict, observation: Observation, args: dict, cancel: Any) -> None: ...


def integer(value, name, minimum=None, maximum=None):
    if isinstance(value, bool) or not isinstance(value, int):
        raise ComputerUseError(f'{name} must be an integer')
    if minimum is not None and value < minimum or maximum is not None and value > maximum:
        raise ComputerUseError(f'{name} is outside the supported range')
    return value
