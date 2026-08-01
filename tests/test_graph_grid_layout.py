from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from src.web_backend.graph_grid_layout import (
    find_available_grid_origin,
    graph_layout_lock,
    grid_rectangle_cells,
    occupied_grid_cells,
    resolve_available_node_ui,
)


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_occupied_grid_cells_include_full_node_rectangle_and_private_nodes(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    _write_json(
        graph_dir / "config.json",
        {"id": "graph", "name": "graph", "layout": {"grid": {"cell_width": 300, "cell_height": 320}}},
    )
    _write_json(
        graph_dir / "wide-private" / "config.json",
        {
            "node_id": "wide-private",
            "type_id": "agent_node",
            "private": True,
            "ui": {"grid_x": 2, "grid_y": 3, "width": 601, "height": 641},
        },
    )

    assert occupied_grid_cells(str(graph_dir)) == grid_rectangle_cells(2, 3, 3, 3)


def test_nearest_origin_skips_any_intersecting_rectangle():
    occupied = grid_rectangle_cells(1, 1, 2, 2)
    origin = find_available_grid_origin(occupied, span_x=2, span_y=2, preferred=(1, 1))

    assert origin == (3, 1)
    assert not (grid_rectangle_cells(*origin, 2, 2) & occupied)


def test_locked_concurrent_allocations_reserve_distinct_rectangles(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    _write_json(graph_dir / "config.json", {"id": "graph", "name": "graph"})

    def allocate(index: int) -> dict[str, int]:
        with graph_layout_lock(str(graph_dir)):
            ui = resolve_available_node_ui(
                str(graph_dir),
                {"grid_x": 0, "grid_y": 0, "width": 601, "height": 321},
            )
            _write_json(
                graph_dir / f"n{index}" / "config.json",
                {"node_id": f"n{index}", "type_id": "agent_node", "ui": ui},
            )
            return ui

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(allocate, range(16)))

    occupied: set[tuple[int, int]] = set()
    for ui in results:
        cells = grid_rectangle_cells(ui["grid_x"], ui["grid_y"], 3, 2)
        assert not (cells & occupied)
        occupied.update(cells)


def test_invalid_legacy_node_coordinates_are_not_silently_accepted(tmp_path: Path):
    graph_dir = tmp_path / "graph"
    _write_json(graph_dir / "config.json", {"id": "graph", "name": "graph"})
    _write_json(
        graph_dir / "legacy" / "config.json",
        {"node_id": "legacy", "type_id": "agent_node", "ui": {"x": 10, "y": 20}},
    )

    try:
        occupied_grid_cells(str(graph_dir))
    except Exception as exc:
        assert "ui.grid_x and ui.grid_y are required" in str(exc)
    else:
        raise AssertionError("legacy absolute coordinates must be rejected")


def test_workspace_board_layout_controls_grid_and_new_node_size(monkeypatch, tmp_path: Path):
    from src import workspace_settings

    monkeypatch.setattr(
        workspace_settings,
        "load_workspace_settings",
        lambda: {
            "boardLayout": {
                "gridCellWidth": 400,
                "gridCellHeight": 500,
                "nodeWidth": 320,
                "nodeHeight": 360,
            }
        },
    )
    graph_dir = tmp_path / "graph"
    _write_json(graph_dir / "config.json", {"id": "graph", "name": "graph"})

    ui = resolve_available_node_ui(str(graph_dir), {"grid_x": 1, "grid_y": 2})

    assert ui == {"grid_x": 1, "grid_y": 2, "width": 320, "height": 360}
