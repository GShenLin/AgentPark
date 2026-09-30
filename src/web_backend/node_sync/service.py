"""Local protocol implementation, called identically by local and remote clients."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import Request

from . import memory, structure
from .blobs import BlobStore, digest, read_json, write_json
from .contracts import ApplyStep, BlobKey, BlobRead, BlobWrite, Bundle, CreateGraph, Prepare, Selection, SyncConflict
from ..node_memory_transaction import run_memory_transaction
from ..runtime_state_memory_store import runtime_state_memory_store
from ..runtime_paths import _get_runtime_root


class SyncService:
    def __init__(self, core, root: Path | None = None):
        self.core = core
        self.root = root or Path(_get_runtime_root()) / ".cache" / "node-sync"
        self.blobs = BlobStore(self.root / "blobs")
        self.instance = memory.identity(self.root)

    def selection(self, selection: Selection, request: Request):
        graph = selection.graph_id
        if graph in {".", ".."} or self.core.graph_runtime._sanitize_graph_id(graph) != graph:
            raise SyncConflict("Graph ID 不合法。")
        self.core.graph_api.require_graph_visible(graph, request)
        directory = Path(self.core.graph_runtime._graph_dir(graph)).resolve()
        if not directory.is_dir():
            raise SyncConflict("Graph 不存在，请先创建目标 Graph。")
        configs = {}
        payload = self.core.node_ops.list_node_instance_configs(graph, request=request)
        for node in payload["nodes"]:
            node_id = node["node_id"]
            if selection.node_id and node_id != selection.node_id:
                continue
            path = Path(self.core.graph_runtime._node_config_path(node_id, graph)).resolve()
            if not path.is_relative_to(directory) or path.parent == directory:
                raise SyncConflict("节点存储路径不合法。")
            configs[node_id] = path
        if selection.node_id and selection.node_id not in configs:
            raise SyncConflict("所选节点不存在或无权访问。")
        return directory, configs

    def memory_dir(self, graph: str, node: str) -> Path:
        return Path(self.core.graph_runtime._node_messages_path(node, graph)).parent

    @staticmethod
    def locked(directory: Path, operation):
        return run_memory_transaction(str(directory / "memory.md"),
                                            str(directory / "messages.jsonl"), operation)

    def export(self, selection: Selection, request):
        directory, configs = self.selection(selection, request)
        graph, groups = structure.export_structure(directory) if not selection.node_id else (None, [])
        if graph is not None:
            from ..graph_output_routes import normalize_output_routes
            normalize_output_routes(graph.get("output_routes"), valid_node_ids=set(configs))
            if any(m["node_id"] not in configs for g in groups for m in g["members"]):
                raise SyncConflict("来源分组引用了不存在或无权读取的节点，不能同步不完整结构。")
            from ..request_access import has_owner_access
            if not has_owner_access(request):
                # A partial public-node projection must not leak hidden members/routes.
                if any(p.parent.name not in configs for p in directory.glob("*/config.json")) or any(g["private"] for g in groups):
                    raise SyncConflict("Graph 含当前连接不可访问的节点或分组，不能导出完整结构。")
        nodes, assets, warnings = [], {}, []
        for node_id, path in configs.items():
            memory_dir = self.memory_dir(selection.graph_id, node_id)
            node, resources, notes = self.locked(memory_dir,
                lambda: memory.export_node(memory_dir, node_id, self.blobs))
            if not selection.node_id:
                node.config = structure.node_configuration(path)
            nodes.append(node)
            assets.update(resources)
            warnings.extend(notes)
        bundle = Bundle(instance=self.instance, selection=selection, graph=graph,
                        groups=groups, nodes=nodes, blobs=assets, warnings=warnings)
        manifest = self.blobs.put_json(bundle.model_dump(exclude_none=True))
        return {"version": 1, "manifest": manifest, "blobs": assets,
                "manifest_bytes": self.blobs.path(manifest).stat().st_size}

    def load_bundle(self, sha: str) -> Bundle:
        path = self.blobs.path(sha)
        if not self.blobs.status(sha)["complete"]:
            raise SyncConflict("导入清单尚未上传完成。")
        bundle = Bundle.model_validate_json(path.read_text(encoding="utf-8"))
        ids = [node.id for node in bundle.nodes]
        if len(ids) != len(set(ids)):
            raise SyncConflict("清单包含重复节点。")
        for node in bundle.nodes:
            record_ids = [e.record.id for e in node.entries]
            origins = [e.origin for e in node.entries]
            if len(record_ids) != len(set(record_ids)) or len(origins) != len(set(origins)):
                raise SyncConflict("清单包含重复消息。")
        for sha, size in bundle.blobs.items():
            status = self.blobs.status(sha)
            if not status["complete"] or status["offset"] != size:
                raise SyncConflict("附件未传完，不能提交。")
        return bundle

    def target_paths(self, target, bundle, request):
        directory, configs = self.selection(target, request)
        if bool(target.node_id) != bool(bundle.selection.node_id):
            raise SyncConflict("两端同步范围不同。")
        if bundle.instance == self.instance and bundle.selection == target:
            raise SyncConflict("来源和目标是同一个 Graph/节点（可能使用了不同远端别名）。")
        if target.node_id:
            if len(bundle.nodes) != 1 or bundle.graph is not None:
                raise SyncConflict("节点同步清单不合法。")
            mapping = {bundle.nodes[0].id: target.node_id}
        else:
            if bundle.graph is None:
                raise SyncConflict("整图同步缺少结构。")
            mapping = {node.id: node.id for node in bundle.nodes}
            from ..request_access import has_owner_access
            if not has_owner_access(request):
                hidden_target = any(p.parent.name not in configs for p in directory.glob("*/config.json"))
                private_source = (bundle.graph.get("private") or any(g["private"] for g in bundle.groups)
                                  or any(n.config and n.config.get("private") for n in bundle.nodes))
                if hidden_target or private_source or any(g["private"] for g in structure.groups(directory)):
                    raise SyncConflict("完整结构包含私有内容，需要在目标机器本机或管理员连接下同步。")
            for node in bundle.nodes:
                if node.id in {".", ".."} or self.core.graph_runtime._sanitize_node_id(node.id) != node.id:
                    raise SyncConflict("节点 ID 不合法。")
                path = Path(self.core.graph_runtime._node_config_path(node.id, target.graph_id)).resolve()
                if not path.is_relative_to(directory) or path.parent == directory:
                    raise SyncConflict("节点路径越界。")
                if path.exists() and node.id not in configs:
                    raise SyncConflict("整图同步包含无权访问的目标节点。")
                configs[node.id] = path
        return directory, configs, mapping

    def prepare(self, payload: Prepare, request):
        bundle = self.load_bundle(payload.manifest)
        directory, configs, mapping = self.target_paths(payload.target, bundle, request)
        result = {"added": 0, "updated": 0, "unchanged": 0, "conflicts": [],
                  "nodes": len(bundle.nodes), "message_bytes": self.blobs.path(payload.manifest).stat().st_size,
                  "attachment_bytes": sum(bundle.blobs.values()), "attachments": len(bundle.blobs),
                  "warnings": list(bundle.warnings), "structure_files": 0, "groups_changed": 0,
                  "structure_changes": []}
        for node in bundle.nodes:
            memory_dir = self.memory_dir(payload.target.graph_id, mapping[node.id])
            counts = self.locked(memory_dir, lambda: memory.merge(memory_dir, node, self.blobs,
                                  memory_dir / "sync_attachments"))
            for key in ("added", "updated", "unchanged"):
                result[key] += counts[key]
            result["conflicts"].extend(counts["conflicts"])
        plan = None
        if bundle.graph is not None:
            plan = structure.plan_structure(directory, payload.target.graph_id, bundle, configs)
            result["structure_files"] = len(plan["files"])
            result["groups_changed"] = plan["groups_changed"]
            result["structure_changes"] = plan["descriptions"]
            result["warnings"].extend(plan["warnings"])
        ticket = uuid.uuid4().hex
        write_json(self.root / "imports" / (ticket + ".json"),
                   {"request": payload.model_dump(), "structure": plan, "result": result, "done": []})
        return {"ticket": ticket, **result}

    def apply(self, ticket: str, index: int, request):
        if not ticket.isalnum() or len(ticket) != 32:
            raise SyncConflict("无效导入标识。")
        path = self.root / "imports" / (ticket + ".json")
        def transaction():
            job = read_json(path)
            if not job:
                raise SyncConflict("导入预览已不存在，请重新预览。")
            if job["result"]["conflicts"]:
                raise SyncConflict("存在记忆冲突，不能提交。")
            payload = Prepare.model_validate(job["request"])
            bundle = self.load_bundle(payload.manifest)
            directory, configs, mapping = self.target_paths(payload.target, bundle, request)
            if index in job["done"]:
                return {"ok": True}
            if index == -1:
                def apply_graph():
                    if job["structure"]:
                        structure.apply_structure(directory, job["structure"], configs)
                runtime_state_memory_store.while_quiescent([str(p) for p in configs.values()], apply_graph)
            elif 0 <= index < len(bundle.nodes):
                if -1 not in job["done"]:
                    raise SyncConflict("必须先提交结构。")
                node = bundle.nodes[index]
                target_id = mapping[node.id]
                memory_dir = self.memory_dir(payload.target.graph_id, target_id)
                def apply_memory():
                    result = self.locked(memory_dir, lambda: memory.merge(memory_dir, node, self.blobs,
                        memory_dir / "sync_attachments", apply=True))
                    if result["conflicts"]:
                        raise SyncConflict("; ".join(result["conflicts"]))
                runtime_state_memory_store.while_quiescent([str(configs[target_id])], apply_memory)
            else:
                raise SyncConflict("无效导入步骤。")
            job["done"].append(index)
            write_json(path, job)
            return {"ok": True}
        from src.file_transaction import run_with_interprocess_lock
        return run_with_interprocess_lock(str(path.with_suffix(".lock")), transaction)

    def protocol(self, operation: str, payload: dict, request):
        self.core.access_api.require_developer(request)
        if operation == "create-graph":
            data = CreateGraph.model_validate(payload)
            if self.core.graph_runtime._sanitize_graph_id(data.id) != data.id:
                raise SyncConflict("Graph ID 只能使用英文字母、数字、横线和下划线。")
            directory = Path(self.core.graph_runtime._graph_dir(data.id))
            from ..graph_grid_layout import graph_layout_lock
            with graph_layout_lock(str(directory)):
                if (directory / "config.json").exists():
                    raise SyncConflict("此 Graph 已存在，请从列表中选择。")
                return self.core.graph_api.save_graph(data.id,
                    {"graph": {"id": data.id, "name": data.name, "output_routes": {}}}, request)
        if operation == "catalog":
            if not payload:
                return {"version": 1, "instance": self.instance,
                        "graphs": self.core.graph_api.list_graphs(request)["graphs"]}
            selection = Selection.model_validate(payload)
            _, paths = self.selection(selection, request)
            return {"nodes": [{"id": n, "name": read_json(p).get("name", n)} for n, p in paths.items()]}
        if operation == "export":
            return self.export(Selection.model_validate(payload), request)
        if operation == "blob-status":
            return self.blobs.status(BlobKey.model_validate(payload).sha)
        if operation == "blob-read":
            data = BlobRead.model_validate(payload)
            return self.blobs.read(data.sha, data.offset)
        if operation == "blob-write":
            data = BlobWrite.model_validate(payload)
            return self.blobs.write(data.sha, data.chunk)
        if operation == "prepare":
            return self.prepare(Prepare.model_validate(payload), request)
        if operation == "apply":
            data = ApplyStep.model_validate(payload)
            return self.apply(data.ticket, data.index, request)
        raise SyncConflict("不支持的同步协议操作，请更新两端 AgentPark。")
