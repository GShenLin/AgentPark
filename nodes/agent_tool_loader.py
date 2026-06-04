from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from src.tool_load_errors import ToolLoadError


@dataclass(frozen=True)
class ConfiguredToolLoadFailure:
    tool_name: str
    message: str


class ConfiguredToolLoadError(RuntimeError):
    def __init__(self, failures: Iterable[ConfiguredToolLoadFailure]):
        self.failures = tuple(failures)
        joined = "; ".join(failure.message for failure in self.failures)
        super().__init__("Configured tools failed to load: " + joined)


def normalize_tool_names(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for item in values:
        name = str(item or "").strip()
        if not name:
            continue
        key = name.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(name)
    return result


def load_configured_tools(agent: object, tool_names: Iterable[str]) -> None:
    failures: list[ConfiguredToolLoadFailure] = []
    for name in normalize_tool_names(list(tool_names or [])):
        try:
            agent.addTool(name)
        except ToolLoadError as exc:
            failures.append(ConfiguredToolLoadFailure(tool_name=name, message=str(exc)))
        except Exception as exc:
            failures.append(
                ConfiguredToolLoadFailure(
                    tool_name=name,
                    message=f"Error loading tool {name}: {type(exc).__name__}: {exc}",
                )
            )
    if failures:
        raise ConfiguredToolLoadError(failures)
