from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Literal, Protocol


@dataclass(frozen=True)
class HarnessDescriptor:
    id: str
    name: str
    node_type: str
    package: str
    executable: str
    transport: str
    homepage: str
    session_support: str
    installation: Literal["npm", "hermes-python"] = "npm"


@dataclass(frozen=True)
class HarnessContext:
    config_path: str
    node_directory: str
    values: dict


@dataclass(frozen=True)
class HarnessResult:
    text: str
    metadata: dict


class HarnessAdapter(Protocol):
    def run(self, text: str, context: HarnessContext) -> HarnessResult: ...


EventHandler = Callable[[dict], None]
