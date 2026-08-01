from __future__ import annotations

import json
from pathlib import Path

from scripts.migrate_node_ui_to_grid import migrate_memories_root
from src.web_backend.graph_grid_layout import grid_rectangle_cells, node_grid_span


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_migration_backs_up_and_reallocates_overlapping_rectangles(tmp_path: Path):
    graph_dir = tmp_path / "default"
    _write_json(graph_dir / "config.json", {"id": "default", "name": "default"})
    for node_id in ("a", "b"):
        _write_json(
            graph_dir / node_id / "config.json",
            {
                "node_id": node_id,
                "type_id": "agent_node",
                "ui": {"x": 300, "y": 320, "width": 601, "height": 321},
            },
        )

    stats = migrate_memories_root(tmp_path, write=True, backup=True)

    assert stats == {"graphs": 1, "nodes": 2, "profiles": 0, "changed_files": 3}
    occupied: set[tuple[int, int]] = set()
    for node_id in ("a", "b"):
        path = graph_dir / node_id / "config.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        assert (path.with_suffix(".json.pre-grid")).exists()
        assert "x" not in payload["ui"] and "y" not in payload["ui"]
        span_x, span_y = node_grid_span(payload["ui"], 300, 320)
        cells = grid_rectangle_cells(payload["ui"]["grid_x"], payload["ui"]["grid_y"], span_x, span_y)
        assert not (cells & occupied)
        occupied.update(cells)

    assert (graph_dir / "config.json.pre-grid").exists()

    second = migrate_memories_root(tmp_path, write=True, backup=True)
    assert second["changed_files"] == 0
