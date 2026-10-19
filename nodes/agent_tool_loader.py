from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Iterable

from src.capabilities.discovery_cache import cached_discovery_value
from src.name_lists import NameListContract
from src.tool.tool_load_errors import ToolLoadError


@dataclass(frozen=True)
class ConfiguredToolLoadFailure:
    tool_name: str
    message: str


class ConfiguredToolLoadError(RuntimeError):
    def __init__(self, failures: Iterable[ConfiguredToolLoadFailure]):
        self.failures = tuple(failures)
        joined = "; ".join(failure.message for failure in self.failures)
        super().__init__("Configured tools failed to load: " + joined)


TOOL_NAME_LIST = NameListContract(
    list_label="tools",
    item_label="tool names",
    error_type=None,
)


def default_tool_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "functions")


def list_available_tool_options(tool_root: str | None = None) -> list[dict[str, str]]:
    root = os.path.abspath(tool_root or default_tool_root())
    if not os.path.isdir(root):
        return []

    from src.tool.toolset_registry import load_toolset_config

    options = cached_discovery_value("tools", root, lambda: _list_available_tool_options_uncached(root))
    names = {item["value"] for item in options}
    config = load_toolset_config()
    options.extend({"value": name, "label": name} for name in config["toolsets"] if name not in names)
    options = [item for item in options if item["value"] not in config["deleted_toolsets"]]
    return sorted(options, key=lambda item: item["label"].casefold())


def _list_available_tool_options_uncached(root: str) -> list[dict[str, str]]:
    options: list[dict[str, str]] = []
    for filename in os.listdir(root):
        if not filename.endswith(".py") or filename == "__init__.py":
            continue
        name = filename[:-3]
        if not name.strip():
            continue
        options.append({"value": name, "label": name})
    options.sort(key=lambda item: item["label"].casefold())
    return options


def load_configured_tools(agent: object, tool_names: Iterable[str]) -> None:
    failures: list[ConfiguredToolLoadFailure] = []
    for name in TOOL_NAME_LIST.parse(list(tool_names or [])):
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
