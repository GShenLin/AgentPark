import os
import re
from copy import deepcopy
from typing import Any

from src.message_protocol import build_text_envelope, envelope_text, normalize_envelope
from src.node_capabilities import NODE_CAPABILITY_LIST

try:
    from src.web_backend import runtime_paths as _runtime_paths

    _get_runtime_root = _runtime_paths._get_runtime_root
    _ORIGINAL_GET_RUNTIME_ROOT = _get_runtime_root
except Exception:
    _runtime_paths = None
    _get_runtime_root = None
    _ORIGINAL_GET_RUNTIME_ROOT = None


class BaseNode:
    name = ""
    description = ""
    input_capabilities = ["text"]
    output_capabilities = ["text"]
    common_config_defaults: dict[str, Any] = {"plugins": [], "skills": [], "working_path": ""}
    common_config_schema: dict[str, dict[str, Any]] = {
        "plugins": {
            "type": "multiselect",
            "label": "Plugins",
            "description": "List of node-scoped plugin bundles loaded from the project plugins folder.",
            "options": [],
        },
        "skills": {
            "type": "multiselect",
            "label": "Skills",
            "description": "List of node-scoped skill names loaded from the project skills folder.",
            "options": [],
        },
        "working_path": {
            "type": "text",
            "label": "Working Path",
            "placeholder": "Select or enter the node working directory",
            "description": "The file explorer opens this directory when the node is selected. Agent nodes receive it as working-directory context.",
        }
    }
    config_defaults: dict[str, Any] = {}
    config_schema: dict[str, dict[str, Any]] = {}
    internal_config_fields: set[str] = set()

    @staticmethod
    def _sanitize_graph_id(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "default"
        safe = re.sub(r"[^a-zA-Z0-9_-]", "", raw)
        return safe or "default"

    @staticmethod
    def _sanitize_node_id(value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return "node"
        safe = re.sub(r'[<>:"/\\|?*]', "_", raw)
        safe = safe.strip()
        return safe or "node"

    def _resolve_memory_path(self, context: dict | None = None) -> str:
        ctx = context if isinstance(context, dict) else {}
        explicit_memory_path = str(ctx.get("memory_path") or "").strip()
        if explicit_memory_path:
            return explicit_memory_path
        graph_id = self._sanitize_graph_id(ctx.get("graph_id"))
        node_id = self._sanitize_node_id(ctx.get("node_instance_id") or ctx.get("agent_id") or ctx.get("node_id"))
        base_dir = ""
        resolver = _get_runtime_root
        if _runtime_paths is not None and resolver is _ORIGINAL_GET_RUNTIME_ROOT:
            resolver = getattr(_runtime_paths, "_get_runtime_root", resolver)
        if callable(resolver):
            try:
                base_dir = str(resolver() or "").strip()
            except Exception:
                base_dir = ""
        if not base_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "memories", graph_id, node_id, "memory.md")

    def _resolve_messages_path(self, context: dict | None = None) -> str:
        ctx = context if isinstance(context, dict) else {}
        explicit_messages_path = str(ctx.get("messages_path") or "").strip()
        if explicit_messages_path:
            return explicit_messages_path
        memory_path = self._resolve_memory_path(context)
        if not memory_path:
            return ""
        return os.path.join(os.path.dirname(memory_path), "messages.jsonl")

    def _text_output(self, text: object, role: str = "assistant") -> dict:
        envelope = build_text_envelope(text, role=role)
        return {
            "display": envelope_text(envelope),
            "routes": [{"output_index": 0, "payload": envelope}],
        }

    def _inject_configured_skills(
        self,
        agent: object,
        context: dict | None = None,
        *,
        node_id: object = "",
        extra_skills: list | tuple | None = None,
    ) -> list:
        from nodes.agent_skill_loader import inject_node_skills

        ctx = context if isinstance(context, dict) else {}
        return inject_node_skills(agent, ctx.get("skills"), node_id=node_id, extra_skills=extra_skills)

    def _persist_input_default(self, message: object, context: dict | None = None) -> None:
        ctx = context if isinstance(context, dict) else {}

        envelope = normalize_envelope(message, default_role="user")
        memory_path = self._resolve_memory_path(ctx)
        messages_path = self._resolve_messages_path(ctx)
        try:
            from src.web_backend.node_memory_store import append_node_memory_entry

            append_node_memory_entry(memory_path, messages_path, "user", envelope)
        except Exception:
            pass

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def get_config_defaults(self, context: dict | None = None) -> dict[str, Any]:
        defaults = getattr(self, "config_defaults", {})
        merged = deepcopy(getattr(self, "common_config_defaults", {}))
        if isinstance(defaults, dict):
            merged.update(deepcopy(defaults))
        return merged

    def get_config_schema(self, context: dict | None = None) -> dict[str, dict[str, Any]]:
        schema = getattr(self, "config_schema", {})
        merged = deepcopy(schema) if isinstance(schema, dict) else {}
        common = deepcopy(getattr(self, "common_config_schema", {}))
        if not isinstance(common, dict):
            common = {}
        capability_payload = None
        if isinstance(common.get("skills"), dict):
            from src.capabilities.registry import CapabilityRegistry

            capability_payload = capability_payload or CapabilityRegistry().discover_payload(context)
            common["skills"]["options"] = list((capability_payload.get("skill") or {}).get("available") or [])
        if isinstance(common.get("plugins"), dict):
            from src.capabilities.registry import CapabilityRegistry

            capability_payload = capability_payload or CapabilityRegistry().discover_payload(context)
            common["plugins"]["options"] = list((capability_payload.get("plugin") or {}).get("available") or [])
        merged.update(common)
        return merged

    def get_internal_config_fields(self, context: dict | None = None) -> set[str]:
        fields = getattr(self, "internal_config_fields", set())
        if not isinstance(fields, set):
            return set()
        return set(fields)

    def apply_config_defaults(self, config: dict, context: dict | None = None) -> None:
        if not isinstance(config, dict):
            return
        for key, value in self.get_config_defaults(context).items():
            if key not in config:
                config[key] = value

    def on_create(self, config: dict, context: dict | None = None) -> None:
        self.apply_config_defaults(config, context)

    def get_capabilities(self, context: dict | None = None) -> dict:
        return {
            "accepts": NODE_CAPABILITY_LIST.parse(getattr(self, "input_capabilities", [])),
            "produces": NODE_CAPABILITY_LIST.parse(getattr(self, "output_capabilities", [])),
        }

    def on_input(self, message: object, context: dict | None = None) -> Any:
        envelope = normalize_envelope(message, default_role="assistant")
        return {
            "display": envelope_text(envelope),
            "routes": [{"output_index": 0, "payload": envelope}],
        }
