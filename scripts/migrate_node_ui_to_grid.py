from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.web_backend.graph_grid_layout import (  # noqa: E402
    find_available_grid_origin,
    graph_layout_lock,
    grid_rectangle_cells,
    node_grid_span,
    normalize_graph_layout,
)


def migrate_memories_root(root: Path, *, write: bool, backup: bool) -> dict[str, int]:
    stats = {"graphs": 0, "nodes": 0, "profiles": 0, "changed_files": 0}
    graph_dirs = sorted(path for path in root.iterdir() if path.is_dir() and _contains_graph_data(path))
    with ExitStack() as locks:
        if write:
            for graph_dir in graph_dirs:
                locks.enter_context(graph_layout_lock(str(graph_dir)))
        _migrate_graph_dirs(graph_dirs, stats=stats, write=write, backup=backup)
    return stats


def _migrate_graph_dirs(
    graph_dirs: list[Path],
    *,
    stats: dict[str, int],
    write: bool,
    backup: bool,
) -> None:
    for graph_dir in graph_dirs:
        graph_config_path = graph_dir / "config.json"
        node_config_paths = []
        for node_config_path in sorted(graph_dir.glob("*/config.json")):
            node = _read_object(node_config_path)
            if str(node.get("node_id") or "").strip() and str(node.get("type_id") or "").strip():
                node_config_paths.append((node_config_path, node))
        graph = _read_object(graph_config_path) if graph_config_path.is_file() else None
        has_graph_config = isinstance(graph, dict) and "id" in graph and "name" in graph
        if not has_graph_config and not node_config_paths:
            continue
        stats["graphs"] += 1
        layout = normalize_graph_layout(graph.get("layout") if has_graph_config else None)
        graph_changed = bool(has_graph_config and graph.get("layout") != layout)
        if has_graph_config:
            graph["layout"] = layout
        occupied: set[tuple[int, int]] = set()
        for node_config_path, node in node_config_paths:
            migrated_ui = _migrate_ui(node.get("ui"), layout=layout, occupied=occupied)
            if node.get("ui") != migrated_ui:
                node["ui"] = migrated_ui
                _write_object(node_config_path, node, write=write, backup=backup)
                stats["changed_files"] += 1
            stats["nodes"] += 1
        if graph_changed and graph is not None:
            _write_object(graph_config_path, graph, write=write, backup=backup)
            stats["changed_files"] += 1


def _contains_graph_data(graph_dir: Path) -> bool:
    graph_config_path = graph_dir / "config.json"
    if graph_config_path.is_file():
        graph = _read_object(graph_config_path)
        if "id" in graph and "name" in graph:
            return True
    for node_config_path in graph_dir.glob("*/config.json"):
        node = _read_object(node_config_path)
        if str(node.get("node_id") or "").strip() and str(node.get("type_id") or "").strip():
            return True
    return False


def migrate_profile_file(path: Path, *, write: bool, backup: bool) -> dict[str, int]:
    profile = _read_object(path)
    graph = profile.get("graph")
    node_configs = profile.get("node_configs")
    if not isinstance(graph, dict) or not isinstance(node_configs, list):
        raise ValueError(f"not a graph profile: {path}")
    layout = normalize_graph_layout(graph.get("layout"))
    changed = graph.get("layout") != layout
    graph["layout"] = layout
    occupied: set[tuple[int, int]] = set()
    positions: dict[str, dict[str, int]] = {}
    for node in node_configs:
        if not isinstance(node, dict):
            continue
        migrated_ui = _migrate_ui(node.get("ui"), layout=layout, occupied=occupied)
        if node.get("ui") != migrated_ui:
            node["ui"] = migrated_ui
            changed = True
        node_id = str(node.get("node_id") or "").strip()
        if node_id:
            positions[node_id] = migrated_ui
    for graph_node in graph.get("nodes") or []:
        if not isinstance(graph_node, dict):
            continue
        node_id = str(graph_node.get("id") or "").strip()
        if node_id in positions and graph_node.get("ui") != positions[node_id]:
            graph_node["ui"] = dict(positions[node_id])
            changed = True
    if changed:
        _write_object(path, profile, write=write, backup=backup)
    return {"graphs": 0, "nodes": len(positions), "profiles": 1, "changed_files": int(changed)}


def migrate_profile_dir(path: Path, *, write: bool, backup: bool) -> dict[str, int]:
    total = {"graphs": 0, "nodes": 0, "profiles": 0, "changed_files": 0}
    for profile_path in sorted(path.glob("*.json")):
        try:
            stats = migrate_profile_file(profile_path, write=write, backup=backup)
        except ValueError:
            continue
        for key in total:
            total[key] += stats[key]
    return total


def _migrate_ui(value: object, *, layout: dict[str, Any], occupied: set[tuple[int, int]]) -> dict[str, int]:
    raw = value if isinstance(value, dict) else {}
    grid = layout["grid"]
    cell_width = int(grid["cell_width"])
    cell_height = int(grid["cell_height"])
    if "grid_x" in raw and "grid_y" in raw:
        preferred = (_non_negative_int(raw["grid_x"]), _non_negative_int(raw["grid_y"]))
    elif "x" in raw and "y" in raw:
        preferred = (
            max(0, int(round(float(raw["x"]) / cell_width))),
            max(0, int(round(float(raw["y"]) / cell_height))),
        )
    else:
        preferred = None
    size_ui: dict[str, int] = {"grid_x": 0, "grid_y": 0}
    for key, minimum in (("width", 230), ("height", 250)):
        if raw.get(key) is not None and str(raw.get(key)).strip():
            size_ui[key] = max(minimum, min(2000, int(round(float(raw[key])))))
    span_x, span_y = node_grid_span(size_ui, cell_width, cell_height)
    grid_x, grid_y = find_available_grid_origin(
        occupied,
        span_x=span_x,
        span_y=span_y,
        preferred=preferred,
        distance_scale=(cell_width, cell_height),
    )
    occupied.update(grid_rectangle_cells(grid_x, grid_y, span_x, span_y))
    return {"grid_x": grid_x, "grid_y": grid_y, **{key: size_ui[key] for key in ("width", "height") if key in size_ui}}


def _non_negative_int(value: object) -> int:
    number = float(value)
    if not number.is_integer() or number < 0:
        raise ValueError("grid coordinate must be a non-negative integer")
    return int(number)


def _read_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON document must be an object: {path}")
    return payload


def _write_object(path: Path, payload: dict[str, Any], *, write: bool, backup: bool) -> None:
    if not write:
        return
    if backup:
        backup_path = path.with_suffix(path.suffix + ".pre-grid")
        if not backup_path.exists():
            shutil.copy2(path, backup_path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temp_path, path)


def main() -> int:
    parser = argparse.ArgumentParser(description="Replace absolute node UI coordinates with strict grid coordinates.")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--root", type=Path, help="AgentPark memories root")
    source.add_argument("--profile", type=Path, help="Standalone graph profile JSON")
    source.add_argument("--profiles-dir", type=Path, help="Directory containing graph profile JSON files")
    parser.add_argument("--write", action="store_true", help="Persist the migration")
    parser.add_argument("--backup", action="store_true", help="Keep one .pre-grid copy beside every changed file")
    args = parser.parse_args()
    if args.root:
        stats = migrate_memories_root(args.root.resolve(), write=args.write, backup=args.backup)
    elif args.profile:
        stats = migrate_profile_file(args.profile.resolve(), write=args.write, backup=args.backup)
    else:
        stats = migrate_profile_dir(args.profiles_dir.resolve(), write=args.write, backup=args.backup)
    mode = "written" if args.write else "dry-run"
    print(
        f"{mode}: graphs={stats['graphs']} nodes={stats['nodes']} "
        f"profiles={stats['profiles']} changed_files={stats['changed_files']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
