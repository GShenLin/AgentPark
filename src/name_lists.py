from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re
from typing import Any


@dataclass(frozen=True)
class NameListContract:
    list_label: str
    item_label: str
    error_type: type[Exception] | None = ValueError
    allow_loose_items: bool = False
    accepted_types: tuple[type, ...] = (list,)
    empty_values: tuple[Any, ...] = (None, "")
    key_func: Callable[[str], str] | None = None

    def parse(self, values: object) -> list[str]:
        if values in self.empty_values:
            return []
        if not isinstance(values, self.accepted_types):
            if self.error_type is None:
                return []
            raise self.error_type(f"{self.list_label} must be a list of {self.item_label}")

        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            if not self.allow_loose_items and not isinstance(item, str):
                if self.error_type is None:
                    continue
                raise self.error_type(f"{self.list_label} must contain only {self.item_label}")
            name = str(item or "").strip()
            if not name:
                continue
            key = self.key_func(name) if self.key_func is not None else name
            if key in seen:
                continue
            seen.add(key)
            result.append(name)
        return result


def path_reference_key(value: str) -> str:
    return re.sub(r"[\\/]+", "/", value)
