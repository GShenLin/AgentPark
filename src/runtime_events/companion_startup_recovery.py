from __future__ import annotations

import os
import json
from typing import Any

from src.file_transaction import atomic_write_text
from src.web_backend.node_config_service import node_config_service
from src.web_backend.node_memory_store import ensure_node_memory_files

from .temporary_receiver_cleanup import runtime_receiver_meta


class CompanionStartupRecovery:
    def __init__(self, core: object, cleanup: object, metrics: object | None = None) -> None:
        self.core = core
        self.cleanup = cleanup
        self.metrics = metrics

    def ensure_canonical_companion(self) -> dict[str, Any]:
        graph_dir = self.core.graph_runtime._graph_dir("Companion")
        node_dir = self.core.graph_runtime._node_dir("Companion", "Companion")
        graph_created = False
        node_created = False
        if not os.path.isdir(graph_dir):
            os.makedirs(graph_dir, exist_ok=True)
            graph_created = True
        graph_config = os.path.join(graph_dir, "config.json")
        if not os.path.exists(graph_config):
            atomic_write_text(
                graph_config,
                json.dumps({"id": "Companion", "name": "Companion", "output_routes": {}}, ensure_ascii=False, indent=2) + "\n",
            )
        if not os.path.isdir(node_dir):
            os.makedirs(node_dir, exist_ok=True)
            node_created = True
        node_config = os.path.join(node_dir, "config.json")
        if not os.path.exists(node_config):
            node_config_service.create_or_replace(
                node_config,
                {
                    "node_id": "Companion",
                    "graph_id": "Companion",
                    "type_id": "agent_node",
                    "name": "Companion",
                    "state": "idle",
                },
            )
            node_created = True
        ensure_node_memory_files(
            self.core.graph_runtime._node_memory_path("Companion", "Companion"),
            self.core.graph_runtime._node_messages_path("Companion", "Companion"),
        )
        return {"graph_created": graph_created, "node_created": node_created}

    def run(self) -> dict[str, Any]:
        summary = {
            "canonical": self.ensure_canonical_companion(),
            "companion_inbox_cleared": 0,
            "temporary_receivers_found": 0,
            "temporary_receivers_cleaned": 0,
            "temporary_receivers_failed": 0,
            "errors": [],
        }
        try:
            inbox = self.cleanup.clear_companion_unexecuted_inbox(graph_id="Companion", node_id="Companion")
            summary["companion_inbox_cleared"] = int(inbox.get("cleared") or 0) if isinstance(inbox, dict) else 0
        except Exception as exc:
            summary["errors"].append(f"clear companion inbox: {type(exc).__name__}: {exc}")

        graph_dir = self.core.graph_runtime._graph_dir("Companion")
        if not graph_dir or not os.path.isdir(graph_dir):
            return summary

        for entry in sorted(os.listdir(graph_dir)):
            config_path = os.path.join(graph_dir, entry, "config.json")
            if not os.path.exists(config_path):
                continue
            try:
                cfg = node_config_service.read_optional_object(config_path)
                if not runtime_receiver_meta(cfg):
                    continue
                summary["temporary_receivers_found"] += 1
                result = self.cleanup.cleanup_now(graph_id="Companion", node_id=entry)
                if isinstance(result, dict) and result.get("ok"):
                    summary["temporary_receivers_cleaned"] += 1
                else:
                    summary["temporary_receivers_failed"] += 1
            except Exception as exc:
                summary["temporary_receivers_failed"] += 1
                summary["errors"].append(f"{entry}: {type(exc).__name__}: {exc}")
        return summary
