import os

from nodes.base_node import BaseNode
from src.generation_output import ResourceOutputField, StructuredOutputSpec, build_generation_output_message
from src.message_protocol import envelope_text
from src.model_texture_content import resolve_model_texture_inputs
from src.node_config_overlay import merge_node_config_overlay
from src.provider_options import build_provider_options_for_support_modes
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

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        options = build_provider_options_for_support_modes(_SUPPORTED_PROVIDER_MODES)
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
        options = build_provider_options_for_support_modes(_SUPPORTED_PROVIDER_MODES)
        if options:
            config["provider_id"] = options[0]["value"]

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        node_id = str(ctx.get("node_instance_id") or ctx.get("node_id") or "model_texture_generation").strip() or "model_texture_generation"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node_dir = os.path.join(base_dir, "memories", graph_id, node_id)
        merged_ctx = merge_node_config_overlay(ctx, node_dir)

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
        self._inject_configured_skills(agent, merged_ctx, node_id=node_id)
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
        output_message = build_generation_output_message(
            result,
            text_fields=("response",),
            resource_fields=(
                ResourceOutputField(
                    name="saved_files",
                    kind="file",
                    source="model_texture_generation",
                    allow_list=True,
                ),
            ),
            structured=StructuredOutputSpec(
                base={"provider_id": provider_id},
                field_names=("task_uuid", "subscription_key", "status"),
                count_field="saved_files",
                count_name="file_count",
            ),
        )
        return {
            "display": envelope_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
