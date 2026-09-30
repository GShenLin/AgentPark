"""Graph structure projection: configuration only, no queues or group deliveries."""
from __future__ import annotations

import copy
from pathlib import Path

from src.agent_groups.contracts import AgentGroup, GroupMember, GroupBounds
from src.agent_groups.repository import GroupRepository, timestamp
from ..graph_output_routes import normalize_output_routes
from ..node_runtime_fields import RUNTIME_STATE_FIELDS
from ..node_config_service import node_config_service
from .blobs import digest, read_json, write_json
from .contracts import SyncConflict

GRAPH_FIELDS = {"name", "working_path", "output_routes", "layout", "node_notes", "private"}
GROUP_FIELDS = {"id", "name", "objective", "bounds", "members", "private"}


def node_configuration(path: Path) -> dict:
    value = read_json(path)
    if not isinstance(value, dict):
        raise SyncConflict(f"节点配置不存在：{path.name}")
    return {k: v for k, v in value.items() if k not in RUNTIME_STATE_FIELDS}


def groups(directory: Path) -> list[dict]:
    if not (directory / "groups.sqlite3").exists():
        return []
    return [g.model_dump(include=GROUP_FIELDS) for g in GroupRepository(directory).list()]


def export_structure(directory: Path):
    value = read_json(directory / "config.json", {})
    return {k: v for k, v in value.items() if k in GRAPH_FIELDS}, groups(directory)


def plan_structure(directory: Path, target_graph: str, bundle, node_paths: dict[str, Path]):
    changes, warnings, descriptions = [], [], []
    all_ids = set(node_paths)
    private_nodes = {n for n, p in node_paths.items() if (read_json(p) or {}).get("private")}
    for node in bundle.nodes:
        incoming = copy.deepcopy(node.config)
        if not isinstance(incoming, dict):
            raise SyncConflict("整图同步缺少节点配置。")
        if set(incoming) & RUNTIME_STATE_FIELDS:
            raise SyncConflict("节点配置不能包含运行状态。")
        incoming["graph_id"], incoming["node_id"] = target_graph, node.id
        if not incoming.get("type_id"):
            raise SyncConflict("节点类型缺失。")
        from ..node_metadata_reader import load_node_instance
        if load_node_instance(incoming["type_id"]) is None:
            raise SyncConflict(f"目标机器未安装节点类型：{incoming['type_id']}")
        node_config_service._validate_capability_fields(incoming, str(node_paths[node.id]))
        incoming = node_config_service._migrate_config(incoming, str(node_paths[node.id]))
        if "ui" in incoming:
            from ..graph_grid_layout import normalize_node_grid_ui
            incoming["ui"] = normalize_node_grid_ui(incoming["ui"])
        path = node_paths[node.id]
        before = read_json(path)
        if before and before.get("private"):
            incoming["private"] = True
        if incoming.get("private"):
            private_nodes.add(node.id)
        if before and before.get("type_id") != incoming["type_id"]:
            raise SyncConflict(f"节点 {node.id} 在两端类型不同，不能覆盖。")
        if before != incoming:
            changes.append({"node": node.id, "before": digest(before), "after": incoming})
            fields = sorted(k for k in set(before or {}) | set(incoming) if (before or {}).get(k) != incoming.get(k))
            descriptions.append(f"{'更新' if before else '新增'}节点 {node.id}：{', '.join(fields)}")
        if incoming.get("provider_id"):
            warnings.append(f"{node.id} 使用目标机器上的 Provider：{incoming['provider_id']}（账号不复制）。")
    graph = read_json(directory / "config.json", {})
    after = copy.deepcopy(graph)
    for field, value in bundle.graph.items():
        if field not in GRAPH_FIELDS:
            raise SyncConflict(f"不支持的 Graph 配置字段：{field}")
        if field in {"output_routes", "node_notes"}:
            copied_ids = {n.id for n in bundle.nodes}
            after[field] = {**{k: v for k, v in graph.get(field, {}).items() if k not in copied_ids}, **value}
        else:
            after[field] = value
    after["id"] = target_graph
    if graph.get("private"):
        after["private"] = True
    after["output_routes"] = normalize_output_routes(after.get("output_routes"), valid_node_ids=all_ids)
    if after != graph:
        changes.append({"node": None, "before": digest(graph), "after": after})
        descriptions.append("更新 Graph：" + ", ".join(k for k in after if after[k] != graph.get(k)))
    before_groups = groups(directory)
    indexed = {g["id"]: g for g in before_groups}
    for group in bundle.groups:
        if set(group) != GROUP_FIELDS:
            raise SyncConflict("分组结构字段不符合协议。")
        GroupBounds.model_validate(group["bounds"])
        members = [GroupMember.model_validate(m) for m in group["members"]]
        if any(m.node_id not in all_ids for m in members):
            raise SyncConflict("分组引用了不存在的节点。")
        value = copy.deepcopy(group)
        if indexed.get(group["id"], {}).get("private"):
            value["private"] = True
        indexed[group["id"]] = value
    owners = {}
    for group in indexed.values():
        for member in group["members"]:
            node_id = member["node_id"]
            if node_id in owners:
                raise SyncConflict(f"节点 {node_id} 将属于多个分组，请先处理目标分组。")
            owners[node_id] = group["id"]
    next_groups = list(indexed.values())
    for index, group in enumerate(next_groups):
        if any(m["node_id"] in private_nodes for m in group["members"]):
            group["private"] = True
        bounds = group["bounds"]
        for other in next_groups[:index]:
            b = other["bounds"]
            if (bounds["x"] < b["x"] + b["width"] and bounds["x"] + bounds["width"] > b["x"]
                    and bounds["y"] < b["y"] + b["height"] and bounds["y"] + bounds["height"] > b["y"]):
                raise SyncConflict(f"分组 {group['name']} 与 {other['name']} 的范围重叠，请使用空目标 Graph 或调整范围。")
    if (directory / "groups.sqlite3").exists():
        for old in GroupRepository(directory).list():
            require_task_owners(old, indexed[old.id])
    for value in bundle.groups:
        if value not in before_groups:
            descriptions.append(f"同步分组 {value['name']}（{len(value['members'])} 个成员）")
    return {"files": changes, "groups_before": digest(before_groups), "groups": next_groups,
            "groups_changed": sum(indexed.get(g["id"]) != g for g in before_groups)
                + len(indexed.keys() - {g["id"] for g in before_groups}), "warnings": warnings,
            "descriptions": descriptions}


def require_task_owners(old: AgentGroup, incoming: dict):
    members = {m["node_id"] for m in incoming["members"]}
    if any(t.status != "done" and t.owner_id and t.owner_id not in members for t in old.tasks):
        raise SyncConflict(f"目标分组 {old.name} 的未完成任务负责人会离组，请先转交或完成这些任务。")


def apply_structure(directory: Path, plan: dict, node_paths: dict[str, Path]):
    # Per-file before/after checks allow safe retry after partial completion.
    for change in plan["files"]:
        path = node_paths[change["node"]] if change["node"] else directory / "config.json"
        current = read_json(path, {} if not change["node"] else None)
        if current == change["after"]:
            continue
        if digest(current) != change["before"]:
            raise SyncConflict("预览后 Graph/节点配置发生变化，请重新预览。")
    current_groups = groups(directory)
    if digest(current_groups) not in {plan["groups_before"], digest(plan["groups"])}:
        raise SyncConflict("预览后分组发生变化，请重新预览。")
    for change in plan["files"]:
        path = node_paths[change["node"]] if change["node"] else directory / "config.json"
        if read_json(path) != change["after"]:
            write_json(path, change["after"])
    if current_groups == plan["groups"]:
        return
    repo = GroupRepository(directory)
    with repo.transaction() as db:
        if db.execute("SELECT 1 FROM deliveries WHERE state='pending' LIMIT 1").fetchone():
            raise SyncConflict("目标分组还有待投递消息，请等待队列完成后重试。")
        current = [AgentGroup.model_validate_json(r[0]) for r in db.execute("SELECT document FROM groups")]
        active = [g.model_dump(include=GROUP_FIELDS) for g in current if not g.dissolved]
        if digest(active) not in {plan["groups_before"], digest(plan["groups"])}:
            raise SyncConflict("提交时分组被其他操作修改。")
        existing = {g.id: g for g in current}
        for value in plan["groups"]:
            if value["id"] in existing:
                require_task_owners(existing[value["id"]], value)
        db.execute("DELETE FROM members")
        for value in plan["groups"]:
            old = existing.get(value["id"])
            if old and old.model_dump(include=GROUP_FIELDS) == value and not old.dissolved:
                group = old
            else:
                group = AgentGroup.model_validate({**value, "tasks": old.model_dump()["tasks"] if old else [],
                    "revision": old.revision + 1 if old else 1, "created_at": old.created_at if old else timestamp(),
                    "updated_at": timestamp(), "dissolved": False})
                repo.save(db, group, bump=False)
            db.executemany("INSERT INTO members(node_id,group_id) VALUES(?,?)",
                           [(m.node_id, group.id) for m in group.members])
        # No events/outbox/queued tasks are created by a structural import.
