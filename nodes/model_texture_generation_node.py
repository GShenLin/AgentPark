import json
import os

from nodes.base_node import BaseNode
from src.config_loader import ConfigLoader
from src.message_protocol import build_resource_part, normalize_envelope
from src.model_texture_content import resolve_model_texture_inputs
from src.providers import create_agent


_SUPPORTED_PROVIDER_MODES = {"model_texture_generation", "texture_generation", "model_generation"}


class Node(BaseNode):
    name = "3D Model Texture Generation"
    description = "Generate textures for an existing 3D model with a reference image."
    input_capabilities = ["text", "resource:image", "resource:file", "resource:url", "structured", "meta"]
    output_capabilities = ["text", "resource:file", "structured", "meta"]

    config_defaults = {
        "provider_id": "",
        "model_path": "",
        "image_path": "",
        "prompt": "",
        "seed": "",
        "reference_scale": "",
        "geometry_file_format": "glb",
        "material": "PBR",
        "resolution": "High",
        "filename_prefix": "generated_textured_model",
    }

    config_schema = {
        "provider_id": {
            "type": "string",
            "label": "provider_id",
            "description": "Only providers whose supportmode contains model_texture_generation should be selected.",
        },
        "model_path": {
            "type": "string",
            "label": "model_path",
            "description": "Required. Existing 3D model path or URL. Hyper3D texture-only API allows up to 10MB.",
        },
        "image_path": {
            "type": "string",
            "label": "image_path",
            "description": "Required. One reference image path or URL for texture generation.",
        },
        "prompt": {
            "type": "text",
            "label": "prompt",
            "description": "Optional texture description.",
        },
        "seed": {"type": "number", "label": "seed", "min": 0, "max": 65535, "step": 1},
        "reference_scale": {
            "type": "number",
            "label": "reference_scale",
            "min": 0.001,
            "step": 0.001,
        },
        "geometry_file_format": {
            "type": "select",
            "label": "geometry_file_format",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "glb", "label": "glb"},
                {"value": "usdz", "label": "usdz"},
                {"value": "fbx", "label": "fbx"},
                {"value": "obj", "label": "obj"},
                {"value": "stl", "label": "stl"},
            ],
        },
        "material": {
            "type": "select",
            "label": "material",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "PBR", "label": "PBR"},
                {"value": "Shaded", "label": "Shaded"},
            ],
        },
        "resolution": {
            "type": "select",
            "label": "resolution",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "Basic", "label": "Basic"},
                {"value": "High", "label": "High"},
            ],
        },
        "filename_prefix": {"type": "string", "label": "filename_prefix"},
    }

    @staticmethod
    def _provider_options() -> list[dict]:
        try:
            providers = ConfigLoader().get_all_providers()
        except Exception:
            providers = {}
        options: list[dict] = []
        if isinstance(providers, dict):
            for provider_id, config in providers.items():
                if not isinstance(config, dict):
                    continue
                modes = config.get("supportmode")
                mode_set = {str(item or "").strip().lower() for item in modes} if isinstance(modes, list) else set()
                if mode_set.intersection(_SUPPORTED_PROVIDER_MODES):
                    text = str(provider_id or "").strip()
                    if text:
                        options.append({"value": text, "label": text})
        options.sort(key=lambda item: item["label"].lower())
        return options

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        options = self._provider_options()
        if options:
            provider_schema = dict(schema.get("provider_id") or {})
            provider_schema["type"] = "select"
            provider_schema["options"] = options
            schema["provider_id"] = provider_schema
        return schema

    def on_create(self, config: dict, context: dict | None = None) -> None:
        super().on_create(config, context)
        if not isinstance(config, dict) or str(config.get("provider_id") or "").strip():
            return
        options = self._provider_options()
        if options:
            config["provider_id"] = options[0]["value"]

    def _load_persisted_config(self, ctx: dict, node_dir: str) -> dict:
        merged = dict(ctx)
        config_path = os.path.join(node_dir, "config.json")
        if not os.path.exists(config_path):
            return merged
        try:
            with open(config_path, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except Exception:
            return merged
        if isinstance(data, dict):
            merged.update(data)
        return merged

    def _build_output_message(self, result: object, *, provider_id: str) -> dict:
        if not isinstance(result, dict):
            return normalize_envelope({"role": "assistant", "parts": [{"type": "text", "text": str(result or "")}]})
        parts: list[dict] = []
        response_text = str(result.get("response") or "").strip()
        if response_text:
            parts.append({"type": "text", "text": response_text})
        saved_files = result.get("saved_files")
        if isinstance(saved_files, str):
            saved_files = [saved_files]
        for path in saved_files if isinstance(saved_files, list) else []:
            uri = str(path or "").strip()
            if uri:
                parts.append(build_resource_part(uri=uri, kind="file", source="model_texture_generation"))
        meta = {"provider_id": provider_id}
        for key in ("task_uuid", "subscription_key", "status"):
            value = result.get(key)
            if value is not None and value != "":
                meta[key] = value
        if isinstance(saved_files, list):
            meta["file_count"] = len(saved_files)
        parts.append({"type": "structured", "data": meta})
        return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        node_id = str(ctx.get("node_instance_id") or ctx.get("node_id") or "model_texture_generation").strip() or "model_texture_generation"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node_dir = os.path.join(base_dir, "memories", graph_id, node_id)
        merged_ctx = self._load_persisted_config(ctx, node_dir)

        provider_id = str(merged_ctx.get("provider_id") or "").strip()
        if not provider_id:
            raise ValueError("provider_id is required")

        model_path, image_path, prompt = resolve_model_texture_inputs(
            message,
            model_path=merged_ctx.get("model_path"),
            image_path=merged_ctx.get("image_path"),
            prompt=merged_ctx.get("prompt"),
        )

        memory_path = os.path.join(node_dir, f"{node_id}.md")
        agent = create_agent(provider_id, memory_file_path=memory_path)
        if not hasattr(agent, "generate_3d_texture"):
            raise ValueError(f"Provider '{provider_id}' does not support 3D texture generation")

        result = agent.generate_3d_texture(
            model_path=model_path,
            image_path=image_path,
            prompt=prompt,
            filename_prefix=str(merged_ctx.get("filename_prefix") or "generated_textured_model").strip() or "generated_textured_model",
            seed=merged_ctx.get("seed"),
            reference_scale=merged_ctx.get("reference_scale"),
            geometry_file_format=merged_ctx.get("geometry_file_format"),
            material=merged_ctx.get("material"),
            resolution=merged_ctx.get("resolution"),
        )
        output_message = self._build_output_message(result, provider_id=provider_id)
        return {
            "display": self._message_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
