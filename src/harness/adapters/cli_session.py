from __future__ import annotations

import json

from src.file_transaction import atomic_write_text


def write_json(path, value: dict) -> None:
    atomic_write_text(str(path), json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_event(line: str) -> dict:
    value = json.loads(line)
    if not isinstance(value, dict) or not isinstance(value.get("type"), str):
        raise ValueError("Harness event must be an object with a string type.")
    return value


def string_field(event: dict, name: str) -> str:
    value = event.get(name)
    if not isinstance(value, str):
        raise ValueError(f"Harness {event.get('type')} event requires string field {name}.")
    return value
