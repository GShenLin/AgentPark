"""Read the authoritative node layout while the caller holds graph_layout_lock."""
import json
from pathlib import Path

from src.agent_groups.contracts import GroupBounds, GroupError
from src.agent_groups.spatial_membership import SpatialMember
from src.board_layout_settings import read_board_layout_settings
from .graph_grid_layout import normalize_node_grid_ui


def read_group_layout(graph_dir: str, bounds: GroupBounds, is_private) -> list[SpatialMember]:
    settings = read_board_layout_settings()
    width, height = settings["gridCellWidth"], settings["gridCellHeight"]
    if (bounds.x < 0 or bounds.y < 0 or bounds.width < width or bounds.height < height
            or any(abs(value / step - round(value / step)) > 1e-9 for value, step in (
                (bounds.x, width), (bounds.y, height), (bounds.width, width), (bounds.height, height)))):
        raise GroupError("组范围必须对齐网格，且至少保留一个完整单元格。")
    result = []
    for path in sorted(Path(graph_dir).glob("*/config.json")):
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(config, dict):
                raise ValueError("node config must be an object")
            if config.get("type_id") != "agent_node":
                continue
            ui = normalize_node_grid_ui(config.get("ui"))
            result.append(SpatialMember(path.parent.name,
                ui["grid_x"] * width + ui.get("width", settings["nodeWidth"]) / 2,
                ui["grid_y"] * height + ui.get("height", settings["nodeHeight"]) / 2,
                is_private(path.parent.name)))
        except (OSError, ValueError) as exc:
            raise GroupError(f"无法读取节点布局 {path.parent.name}: {exc}") from exc
    return result
