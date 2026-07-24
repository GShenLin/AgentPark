import importlib
import os
import pkgutil

from fastapi import Request

from nodes.agent_node_modes import MODE_ORDER
from src.config_loader import ConfigLoader
from src.provider_options import PROVIDER_VISIBILITY_CONTEXT_KEY

from . import runtime_paths
from .node_metadata_reader import NodeMetadataError
from .node_metadata_reader import load_node_instance
from .node_metadata_reader import read_node_internal_fields
from .node_metadata_reader import read_node_schema
from .service_host import HostBoundService
from .route_parser import NodeRouteParser
from .request_access import is_local_request
from .shared import HTTPException, _list_node_metas, _read_node_capabilities


class NodeCatalog(HostBoundService):
    def list_tools(self):
        tools = []
        functions_dir = runtime_paths._get_functions_dir()
        try:
            if functions_dir and os.path.isdir(functions_dir):
                for filename in os.listdir(functions_dir):
                    if filename.endswith(".py") and filename != "__init__.py":
                        tools.append(filename[:-3])
            else:
                functions_pkg = importlib.import_module("functions")
                for mod in pkgutil.iter_modules(getattr(functions_pkg, "__path__", [])):
                    if mod.name != "__init__":
                        tools.append(mod.name)
            tools.sort()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to list tools: {type(exc).__name__}: {exc}")
        return {"tools": tools}

    def list_nodes(self):
        return {"nodes": _list_node_metas(runtime_paths._get_nodes_dir())}

    def get_node_template(
        self,
        type_id: str,
        provider_id: str = "",
        request: Request = None,
    ):
        if not isinstance(type_id, str) or not type_id.strip():
            raise HTTPException(status_code=400, detail="type_id is required")

        safe_type_id = type_id.strip()
        try:
            node = load_node_instance(safe_type_id)
        except NodeMetadataError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        if node is None:
            raise HTTPException(status_code=404, detail="node type not found")

        cfg: dict = {
            "node_id": "template",
            "type_id": safe_type_id,
            "name": str(getattr(node, "name", type_id) or type_id),
            "graph_id": self.default_graph_id,
        }
        context_overrides = {PROVIDER_VISIBILITY_CONTEXT_KEY: is_local_request(request)}
        safe_provider_id = str(provider_id or "").strip()
        if safe_type_id in {"agent_node", "codex_node"} and safe_provider_id:
            try:
                provider_config = ConfigLoader().get_provider_config(safe_provider_id)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            raw_support_modes = provider_config.get("supportmode")
            support_modes = (
                [str(item).strip() for item in raw_support_modes if str(item).strip() in MODE_ORDER]
                if isinstance(raw_support_modes, list)
                else []
            )
            if safe_type_id == "codex_node" and not any(
                mode in {"chat", "imagechat"} for mode in support_modes
            ):
                raise HTTPException(
                    status_code=400,
                    detail=f"Provider {safe_provider_id!r} does not declare chat or imagechat support.",
                )
            context_overrides["support_modes"] = support_modes
            context_overrides["provider_id"] = safe_provider_id
        try:
            self.graph_runtime._try_init_node_config(
                safe_type_id,
                cfg,
                self.default_graph_id,
                "template",
                context_overrides,
                node=node,
            )
        except NodeMetadataError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        context = self.graph_runtime._build_node_context(
            safe_type_id,
            self.default_graph_id,
            "template",
            cfg,
            context_overrides,
        )

        try:
            schema = read_node_schema(node, context)
            internal_fields = read_node_internal_fields(node, context)
        except NodeMetadataError as exc:
            raise HTTPException(status_code=500, detail=str(exc))
        fields: dict[str, object] = {}
        accepts, produces = _read_node_capabilities(node, None)

        for key, value in cfg.items():
            if (
                isinstance(key, str)
                and key.strip()
                and key not in self.reserved_node_fields
                and not key.startswith("_")
                and key not in internal_fields
            ):
                fields[key] = value

        if isinstance(schema, dict):
            for key in schema.keys():
                if isinstance(key, str) and key.strip() and key not in self.reserved_node_fields and key not in fields:
                    fields[key] = ""

        payload = {
            "type_id": safe_type_id,
            "name": str(getattr(node, "name", type_id) or type_id),
            "description": str(getattr(node, "description", "") or ""),
            "input_num": NodeRouteParser.parse_port_count(cfg.get("input_num"), default=1),
            "output_num": NodeRouteParser.parse_port_count(cfg.get("output_num"), default=1),
            "accepts": accepts,
            "produces": produces,
            "schema": schema,
            "fields": fields,
        }
        if safe_type_id == "agent_node":
            payload["support_modes"] = list(context_overrides.get("support_modes") or [])
        return payload
