import os
import re
import json
from copy import deepcopy
from datetime import datetime
from typing import Any

from src.message_protocol import build_text_envelope, envelope_text, normalize_envelope

try:
    from src.web_backend.runtime_paths import _get_runtime_root
except Exception:
    _get_runtime_root = None


class BaseNode:
    name = ""
    description = ""
    input_capabilities = ["text"]
    output_capabilities = ["text"]
    common_config_defaults: dict[str, Any] = {"working_path": ""}
    common_config_schema: dict[str, dict[str, Any]] = {
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
    def _normalize_capabilities(values: object) -> list[str]:
        if not isinstance(values, (list, tuple)):
            return []
        result: list[str] = []
        seen: set[str] = set()
        for item in values:
            text = str(item or "").strip()
            if not text:
                continue
            key = text.lower()
            if key in seen:
                continue
            seen.add(key)
            result.append(text)
        return result

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
        graph_id = self._sanitize_graph_id(ctx.get("graph_id"))
        node_id = self._sanitize_node_id(ctx.get("node_instance_id") or ctx.get("agent_id") or ctx.get("node_id"))
        base_dir = ""
        if callable(_get_runtime_root):
            try:
                base_dir = str(_get_runtime_root() or "").strip()
            except Exception:
                base_dir = ""
        if not base_dir:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(base_dir, "memories", graph_id, node_id, f"{node_id}.md")

    def _resolve_messages_path(self, context: dict | None = None) -> str:
        memory_path = self._resolve_memory_path(context)
        if not memory_path:
            return ""
        return os.path.join(os.path.dirname(memory_path), "messages.jsonl")

    def _normalize_message(self, value: object, default_role: str = "user") -> dict:
        return normalize_envelope(value, default_role=default_role)

    def _message_text(self, value: object) -> str:
        return envelope_text(value)

    def _text_output(self, text: object, role: str = "assistant") -> dict:
        envelope = build_text_envelope(text, role=role)
        return {
            "display": self._message_text(envelope),
            "routes": [{"output_index": 0, "payload": envelope}],
        }

    def _persist_input_default(self, message: object, context: dict | None = None) -> None:
        ctx = context if isinstance(context, dict) else {}

        envelope = self._normalize_message(message, default_role="user")
        payload = self._message_text(envelope)
        memory_path = self._resolve_memory_path(ctx)
        messages_path = self._resolve_messages_path(ctx)

        if memory_path:
            try:
                os.makedirs(os.path.dirname(memory_path), exist_ok=True)
                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                entry = f"\n**[{timestamp}] user**: {payload}\n"
                with open(memory_path, "a", encoding="utf-8") as f:
                    f.write(entry)
            except Exception:
                pass

        if messages_path:
            try:
                os.makedirs(os.path.dirname(messages_path), exist_ok=True)
                with open(messages_path, "a", encoding="utf-8") as f:
                    f.write(
                        json.dumps(
                            {
                                "id": str(envelope.get("id") or ""),
                                "role": "user",
                                "parts": envelope.get("parts") if isinstance(envelope.get("parts"), list) else [],
                                "created_at": str(envelope.get("created_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f")),
                            },
                            ensure_ascii=False,
                        )
                        + "\n"
                    )
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
            "accepts": self._normalize_capabilities(getattr(self, "input_capabilities", [])),
            "produces": self._normalize_capabilities(getattr(self, "output_capabilities", [])),
        }

    def on_input(self, message: object, context: dict | None = None) -> Any:
        envelope = self._normalize_message(message, default_role="assistant")
        return {
            "display": self._message_text(envelope),
            "routes": [{"output_index": 0, "payload": envelope}],
        }
