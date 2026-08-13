from __future__ import annotations

from typing import Any

from . import workspace_settings


DEFAULT_GRID_CELL_WIDTH = 300
DEFAULT_GRID_CELL_HEIGHT = 320
MIN_GRID_CELL_WIDTH = 230
MIN_GRID_CELL_HEIGHT = 250
MAX_GRID_CELL_SIZE = 2000

DEFAULT_NODE_WIDTH = 230
DEFAULT_NODE_HEIGHT = 250
MIN_NODE_WIDTH = 50
MIN_NODE_HEIGHT = 50
MAX_NODE_WIDTH = 720
MAX_NODE_HEIGHT = 760


def normalize_board_layout_settings(value: object) -> dict[str, int]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("config.json field 'boardLayout' must be an object")
    return {
        "gridCellWidth": _bounded_integer(
            value.get("gridCellWidth", DEFAULT_GRID_CELL_WIDTH),
            field="config.json field 'boardLayout.gridCellWidth'",
            minimum=MIN_GRID_CELL_WIDTH,
            maximum=MAX_GRID_CELL_SIZE,
        ),
        "gridCellHeight": _bounded_integer(
            value.get("gridCellHeight", DEFAULT_GRID_CELL_HEIGHT),
            field="config.json field 'boardLayout.gridCellHeight'",
            minimum=MIN_GRID_CELL_HEIGHT,
            maximum=MAX_GRID_CELL_SIZE,
        ),
        "nodeWidth": _bounded_integer(
            value.get("nodeWidth", DEFAULT_NODE_WIDTH),
            field="config.json field 'boardLayout.nodeWidth'",
            minimum=MIN_NODE_WIDTH,
            maximum=MAX_NODE_WIDTH,
        ),
        "nodeHeight": _bounded_integer(
            value.get("nodeHeight", DEFAULT_NODE_HEIGHT),
            field="config.json field 'boardLayout.nodeHeight'",
            minimum=MIN_NODE_HEIGHT,
            maximum=MAX_NODE_HEIGHT,
        ),
    }


def read_board_layout_settings(payload: dict[str, Any] | None = None) -> dict[str, int]:
    settings = workspace_settings.load_workspace_settings() if payload is None else payload
    if not isinstance(settings, dict):
        raise ValueError("config/config.json must contain a top-level object")
    return normalize_board_layout_settings(settings.get("boardLayout"))


def board_layout_graph_payload(settings: dict[str, int]) -> dict[str, dict[str, int]]:
    return {
        "grid": {
            "cell_width": int(settings["gridCellWidth"]),
            "cell_height": int(settings["gridCellHeight"]),
        }
    }


def _bounded_integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}") from exc
    if not number.is_integer() or number < minimum or number > maximum:
        raise ValueError(f"{field} must be an integer between {minimum} and {maximum}")
    return int(number)


__all__ = [
    "DEFAULT_GRID_CELL_HEIGHT",
    "DEFAULT_GRID_CELL_WIDTH",
    "DEFAULT_NODE_HEIGHT",
    "DEFAULT_NODE_WIDTH",
    "MAX_GRID_CELL_SIZE",
    "MAX_NODE_HEIGHT",
    "MAX_NODE_WIDTH",
    "MIN_GRID_CELL_HEIGHT",
    "MIN_GRID_CELL_WIDTH",
    "MIN_NODE_HEIGHT",
    "MIN_NODE_WIDTH",
    "board_layout_graph_payload",
    "normalize_board_layout_settings",
    "read_board_layout_settings",
]
