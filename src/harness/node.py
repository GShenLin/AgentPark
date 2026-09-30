"""Common graph boundary for real, independently registered Harness nodes."""
from __future__ import annotations

import os

from nodes.agent_message_adapter import append_channel_meta, build_response_metadata_message, extract_channel_meta
from nodes.base_node import BaseNode
from src.config_loader import ConfigLoader
from src.harness.contracts import HarnessContext
from src.harness.install_manager import runtime_lease
from src.harness.registry import create_adapter
from src.harness.reasoning_config import reasoning_options
from src.message_protocol import build_text_envelope, envelope_text, normalize_envelope
from src.provider_models import provider_model_ids
from src.provider_options import build_provider_options_for_support_modes, provider_options_include_private


class HarnessNode(BaseNode):
    harness_id = ""
    provider_reasoning_options = False
    support_modes = ("chat",)
    input_capabilities = ["text", "resource:image", "resource:video", "resource:audio",
                          "resource:doc", "resource:file", "resource:url", "structured", "meta"]
    output_capabilities = ["text", "structured", "tool_call", "meta"]
    common_config_defaults = {"working_path": ""}
    common_config_schema = {"working_path": {
        **BaseNode.common_config_schema["working_path"],
        "description": "Harness working directory; empty uses this node's own workspace.",
    }}

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        schema["provider_id"] = {
            "type": "select", "label": "provider_id",
            "options": build_provider_options_for_support_modes(
                set(self.support_modes), include_private=provider_options_include_private(context)),
        }
        provider_id = str((context or {}).get("provider_id") or "").strip()
        models = provider_model_ids(ConfigLoader().get_provider_config(provider_id)) if provider_id else []
        schema["model"] = {"type": "select", "label": "model",
                           "description": "Model from the selected Provider; empty uses its first model.",
                           "options": [{"value": model, "label": model} for model in models]}
        if self.provider_reasoning_options:
            config = ConfigLoader().get_provider_config(provider_id) if provider_id else {}
            if (context or {}).get("model"):
                config = {**config, "model": context["model"]}
            schema["reasoning_effort"] = {**self.config_schema["reasoning_effort"], "options": [
                {"value": "", "label": "运行时默认"},
                *[{"value": effort, "label": effort} for effort in reasoning_options(config)],
            ]}
        return schema

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        input_message = normalize_envelope(message, default_role="user")
        text = envelope_text(input_message).strip()
        if not text:
            raise ValueError(f"{self.name} node input contains no text or representable resource.")
        explicit = str(ctx.get("node_config_path") or "").strip()
        config_path = os.path.abspath(explicit) if explicit else os.path.join(
            os.path.dirname(self._resolve_memory_path(ctx)), "config.json")
        with runtime_lease(self.harness_id):
            response = create_adapter(self.harness_id).run(
                text, HarnessContext(config_path, os.path.dirname(config_path), ctx))
        output = append_channel_meta(build_text_envelope(response.text, role="assistant"),
                                     extract_channel_meta(input_message))
        result = {"display": envelope_text(output), "display_message": output,
                  "routes": [{"output_index": 0, "payload": output}]}
        metadata = build_response_metadata_message(response.metadata, scope="final_assistant",
                                                  target_message_id=output.get("id"), fields=("response_metadata",))
        if metadata is not None:
            result["memory_sidecars"] = [metadata]
        return result
