from __future__ import annotations

import json
import heapq
import math
import os
import threading
import time
from contextlib import contextmanager
from typing import Any, Iterator

from src.board_layout_settings import (
    DEFAULT_GRID_CELL_HEIGHT,
    DEFAULT_GRID_CELL_WIDTH,
    DEFAULT_NODE_HEIGHT,
    DEFAULT_NODE_WIDTH,
    MAX_GRID_CELL_SIZE,
    MIN_GRID_CELL_HEIGHT,
    MIN_GRID_CELL_WIDTH,
    board_layout_graph_payload,
    read_board_layout_settings,
)

DEFAULT_GRID_COLUMNS = 4

_thread_locks_guard = threading.Lock()
_thread_locks: dict[str, threading.RLock] = {}


class GridLayoutDataError(RuntimeError):
    pass


def normalize_graph_layout(value: object) -> dict[str, Any]:
    if value is None:
        value = {}
    if not isinstance(value, dict):
        raise ValueError("graph layout must be an object")
    grid = value.get("grid")
    if grid is None:
        grid = {}
    if not isinstance(grid, dict):
        raise ValueError("graph layout.grid must be an object")
    return {
        "grid": {
            "cell_width": _bounded_integer(
                grid.get("cell_width", DEFAULT_GRID_CELL_WIDTH),
                field="graph layout.grid.cell_width",
                minimum=MIN_GRID_CELL_WIDTH,
                maximum=MAX_GRID_CELL_SIZE,
            ),
            "cell_height": _bounded_integer(
                grid.get("cell_height", DEFAULT_GRID_CELL_HEIGHT),
                field="graph layout.grid.cell_height",
                minimum=MIN_GRID_CELL_HEIGHT,
                maximum=MAX_GRID_CELL_SIZE,
            ),
        }
    }


def normalize_node_grid_ui(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        raise ValueError("ui must be object")
    if "grid_x" not in value or "grid_y" not in value:
        raise ValueError("ui.grid_x and ui.grid_y are required")
    normalized = {
        "grid_x": _non_negative_integer(value.get("grid_x"), "ui.grid_x"),
        "grid_y": _non_negative_integer(value.get("grid_y"), "ui.grid_y"),
    }
    if value.get("width") is not None and str(value.get("width")).strip():
        normalized["width"] = _bounded_integer(
            value.get("width"),
            field="ui.width",
            minimum=MIN_GRID_CELL_WIDTH,
            maximum=MAX_GRID_CELL_SIZE,
        )
    if value.get("height") is not None and str(value.get("height")).strip():
        normalized["height"] = _bounded_integer(
            value.get("height"),
            field="ui.height",
            minimum=MIN_GRID_CELL_HEIGHT,
            maximum=MAX_GRID_CELL_SIZE,
        )
    return normalized


def graph_grid_settings(graph_dir: str) -> tuple[int, int]:
    try:
        settings = read_board_layout_settings()
    except ValueError as exc:
        raise GridLayoutDataError(f"invalid board layout settings: {exc}") from exc
    return int(settings["gridCellWidth"]), int(settings["gridCellHeight"])


def workspace_graph_layout() -> dict[str, dict[str, int]]:
    return board_layout_graph_payload(read_board_layout_settings())


def node_grid_span(
    ui: dict[str, int],
    cell_width: int,
    cell_height: int,
    *,
    default_width: int = DEFAULT_NODE_WIDTH,
    default_height: int = DEFAULT_NODE_HEIGHT,
) -> tuple[int, int]:
    width = int(ui.get("width", default_width))
    height = int(ui.get("height", default_height))
    return max(1, math.ceil(width / cell_width)), max(1, math.ceil(height / cell_height))


def occupied_grid_cells(
    graph_dir: str,
    *,
    exclude_node_ids: set[str] | None = None,
) -> set[tuple[int, int]]:
    occupied: set[tuple[int, int]] = set()
    if not graph_dir or not os.path.isdir(graph_dir):
        return occupied
    excluded = {str(item).strip() for item in (exclude_node_ids or set()) if str(item).strip()}
    settings = read_board_layout_settings()
    cell_width = int(settings["gridCellWidth"])
    cell_height = int(settings["gridCellHeight"])
    for entry in os.listdir(graph_dir):
        if entry in excluded:
            continue
        config_path = os.path.join(graph_dir, entry, "config.json")
        if not os.path.isfile(config_path):
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except FileNotFoundError:
            continue
        except (OSError, json.JSONDecodeError) as exc:
            raise GridLayoutDataError(f"failed to read node grid position: {config_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise GridLayoutDataError(f"node config must be an object: {config_path}")
        try:
            ui = normalize_node_grid_ui(payload.get("ui"))
        except ValueError as exc:
            raise GridLayoutDataError(f"invalid node grid position: {config_path}: {exc}") from exc
        span_x, span_y = node_grid_span(
            ui,
            cell_width,
            cell_height,
            default_width=int(settings["nodeWidth"]),
            default_height=int(settings["nodeHeight"]),
        )
        occupied.update(grid_rectangle_cells(ui["grid_x"], ui["grid_y"], span_x, span_y))
    return occupied


def repair_missing_node_grid_positions(
    graph_dir: str,
    *,
    exclude_node_ids: set[str] | None = None,
) -> list[str]:
    """Persist deterministic grid positions for node configs that predate grid UI.

    A completely absent ``ui`` value is allocated normally. The explicit legacy
    ``{"x": ..., "y": ...}`` contract is migrated from absolute pixels to the
    current grid. Other malformed or partially migrated UI remains an error.
    """
    if not graph_dir or not os.path.isdir(graph_dir):
        return []
    excluded = {str(item).strip() for item in (exclude_node_ids or set()) if str(item).strip()}
    settings = read_board_layout_settings()
    cell_width = int(settings["gridCellWidth"])
    cell_height = int(settings["gridCellHeight"])
    occupied: set[tuple[int, int]] = set()
    missing: list[tuple[str, str, dict[str, Any], dict[str, int] | None]] = []

    for entry in sorted(os.listdir(graph_dir)):
        if entry in excluded:
            continue
        config_path = os.path.join(graph_dir, entry, "config.json")
        if not os.path.isfile(config_path):
            continue
        try:
            with open(config_path, "r", encoding="utf-8") as handle:
                payload = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            raise GridLayoutDataError(f"failed to read node grid position: {config_path}: {exc}") from exc
        if not isinstance(payload, dict):
            raise GridLayoutDataError(f"node config must be an object: {config_path}")
        if payload.get("ui") is None:
            missing.append((entry, config_path, payload, None))
            continue
        legacy_ui = _normalize_legacy_absolute_ui(payload.get("ui"), cell_width, cell_height)
        if legacy_ui is not None:
            missing.append((entry, config_path, payload, legacy_ui))
            continue
        try:
            ui = normalize_node_grid_ui(payload.get("ui"))
        except ValueError as exc:
            raise GridLayoutDataError(f"invalid node grid position: {config_path}: {exc}") from exc
        span_x, span_y = node_grid_span(
            ui,
            cell_width,
            cell_height,
            default_width=int(settings["nodeWidth"]),
            default_height=int(settings["nodeHeight"]),
        )
        occupied.update(grid_rectangle_cells(ui["grid_x"], ui["grid_y"], span_x, span_y))

    repaired: list[str] = []
    for node_id, config_path, payload, requested_ui in missing:
        size_source = requested_ui or {
            "grid_x": 0,
            "grid_y": 0,
            "width": int(settings["nodeWidth"]),
            "height": int(settings["nodeHeight"]),
        }
        span_x, span_y = node_grid_span(size_source, cell_width, cell_height)
        preferred = (
            (requested_ui["grid_x"], requested_ui["grid_y"])
            if requested_ui is not None
            else None
        )
        grid_x, grid_y = find_available_grid_origin(
            occupied,
            span_x=span_x,
            span_y=span_y,
            preferred=preferred,
            distance_scale=(cell_width, cell_height),
        )
        ui = {
            "width": int(settings["nodeWidth"]),
            "height": int(settings["nodeHeight"]),
            **(requested_ui or {}),
            "grid_x": grid_x,
            "grid_y": grid_y,
        }
        payload["ui"] = ui
        _write_json_object(config_path, payload)
        occupied.update(grid_rectangle_cells(grid_x, grid_y, span_x, span_y))
        repaired.append(node_id)
    return repaired


def _normalize_legacy_absolute_ui(value: object, cell_width: int, cell_height: int) -> dict[str, int] | None:
    if not isinstance(value, dict):
        return None
    if "grid_x" in value or "grid_y" in value:
        return None
    if "x" not in value and "y" not in value:
        return None
    if "x" not in value or "y" not in value:
        raise ValueError("legacy ui.x and ui.y are both required")
    x = _finite_number(value.get("x"), "legacy ui.x")
    y = _finite_number(value.get("y"), "legacy ui.y")
    migrated: dict[str, object] = {
        "grid_x": max(0, math.floor((x / cell_width) + 0.5)),
        "grid_y": max(0, math.floor((y / cell_height) + 0.5)),
    }
    if value.get("width") is not None:
        migrated["width"] = value.get("width")
    if value.get("height") is not None:
        migrated["height"] = value.get("height")
    return normalize_node_grid_ui(migrated)


def grid_rectangle_cells(grid_x: int, grid_y: int, span_x: int, span_y: int) -> set[tuple[int, int]]:
    return {
        (x, y)
        for y in range(grid_y, grid_y + max(1, span_y))
        for x in range(grid_x, grid_x + max(1, span_x))
    }


def find_available_grid_origin(
    occupied: set[tuple[int, int]],
    *,
    span_x: int = 1,
    span_y: int = 1,
    preferred: tuple[int, int] | None = None,
    distance_scale: tuple[int, int] = (1, 1),
) -> tuple[int, int]:
    def available(origin: tuple[int, int]) -> bool:
        return not (grid_rectangle_cells(origin[0], origin[1], span_x, span_y) & occupied)

    if preferred is None:
        index = 0
        while True:
            candidate = (index % DEFAULT_GRID_COLUMNS, index // DEFAULT_GRID_COLUMNS)
            if available(candidate):
                return candidate
            index += 1

    preferred_x = max(0, int(preferred[0]))
    preferred_y = max(0, int(preferred[1]))
    scale_x = max(1, int(distance_scale[0]))
    scale_y = max(1, int(distance_scale[1]))
    candidates: list[tuple[int, int, int]] = [(0, preferred_y, preferred_x)]
    queued = {(preferred_x, preferred_y)}
    while candidates:
        _, y, x = heapq.heappop(candidates)
        candidate = (x, y)
        if available(candidate):
            return candidate
        for next_x, next_y in ((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)):
            if next_x < 0 or next_y < 0 or (next_x, next_y) in queued:
                continue
            queued.add((next_x, next_y))
            distance_squared = (
                ((next_x - preferred_x) * scale_x) ** 2
                + ((next_y - preferred_y) * scale_y) ** 2
            )
            heapq.heappush(candidates, (distance_squared, next_y, next_x))
    raise RuntimeError("failed to find an available grid origin")


def resolve_available_node_ui(
    graph_dir: str,
    requested_ui: object = None,
    *,
    exclude_node_ids: set[str] | None = None,
) -> dict[str, int]:
    requested = normalize_node_grid_ui(requested_ui) if requested_ui is not None else None
    settings = read_board_layout_settings()
    cell_width = int(settings["gridCellWidth"])
    cell_height = int(settings["gridCellHeight"])
    size_source = {
        "grid_x": 0,
        "grid_y": 0,
        "width": int(settings["nodeWidth"]),
        "height": int(settings["nodeHeight"]),
        **(requested or {}),
    }
    span_x, span_y = node_grid_span(size_source, cell_width, cell_height)
    occupied = occupied_grid_cells(graph_dir, exclude_node_ids=exclude_node_ids)
    preferred = (requested["grid_x"], requested["grid_y"]) if requested is not None else None
    grid_x, grid_y = find_available_grid_origin(
        occupied,
        span_x=span_x,
        span_y=span_y,
        preferred=preferred,
        distance_scale=(cell_width, cell_height),
    )
    return {
        "grid_x": grid_x,
        "grid_y": grid_y,
        "width": int(size_source["width"]),
        "height": int(size_source["height"]),
    }


@contextmanager
def graph_layout_lock(graph_dir: str, timeout_seconds: float = 30.0) -> Iterator[None]:
    safe_dir = os.path.abspath(graph_dir)
    os.makedirs(safe_dir, exist_ok=True)
    with _thread_locks_guard:
        thread_lock = _thread_locks.setdefault(safe_dir, threading.RLock())
    with thread_lock:
        lock_path = os.path.join(safe_dir, ".layout.lock")
        with open(lock_path, "a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            _lock_file(handle, timeout_seconds)
            try:
                yield
            finally:
                _unlock_file(handle)


def _lock_file(handle: Any, timeout_seconds: float) -> None:
    deadline = time.monotonic() + max(0.1, timeout_seconds)
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        while True:
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out acquiring graph layout lock")
                time.sleep(0.05)
    else:
        import fcntl

        while True:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError("timed out acquiring graph layout lock")
                time.sleep(0.05)


def _unlock_file(handle: Any) -> None:
    handle.seek(0)
    if os.name == "nt":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _non_negative_integer(value: object, field: str) -> int:
    number = _integer(value, field)
    if number < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return number


def _bounded_integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    number = _integer(value, field)
    if number < minimum or number > maximum:
        raise ValueError(f"{field} must be between {minimum} and {maximum}")
    return number


def _integer(value: object, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an integer")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an integer") from exc
    if not math.isfinite(number) or not number.is_integer():
        raise ValueError(f"{field} must be an integer")
    return int(number)


def _finite_number(value: object, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be a finite number")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be a finite number") from exc
    if not math.isfinite(number):
        raise ValueError(f"{field} must be a finite number")
    return number


def _write_json_object(path: str, payload: dict[str, Any]) -> None:
    temp_path = f"{path}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_path, path)
    except OSError as exc:
        try:
            os.remove(temp_path)
        except OSError:
            pass
        raise GridLayoutDataError(f"failed to persist node grid position: {path}: {exc}") from exc


__all__ = [
    "DEFAULT_GRID_CELL_HEIGHT",
    "DEFAULT_GRID_CELL_WIDTH",
    "GridLayoutDataError",
    "find_available_grid_origin",
    "graph_grid_settings",
    "graph_layout_lock",
    "grid_rectangle_cells",
    "node_grid_span",
    "normalize_graph_layout",
    "normalize_node_grid_ui",
    "occupied_grid_cells",
    "repair_missing_node_grid_positions",
    "resolve_available_node_ui",
    "workspace_graph_layout",
]
