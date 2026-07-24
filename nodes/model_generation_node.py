import os

from nodes.base_node import BaseNode
from src.generation_output import ResourceOutputField, StructuredOutputSpec, build_generation_output_message
from src.message_protocol import envelope_text
from src.model_generation_content import resolve_model_generation_inputs
from src.node_config_overlay import merge_node_config_overlay
from src.provider_options import (
    build_provider_options_for_support_modes,
    provider_options_include_private,
)
from src.providers import create_agent


_SUPPORTED_PROVIDER_MODES = {"model_generation", "3d_model_generation", "rodin_generation"}


class Node(BaseNode):
    name = "3D Model Generation"
    description = "Generate downloadable 3D model assets with Hyper3D Rodin."
    input_capabilities = ["text", "resource:image", "resource:file", "resource:url", "structured", "meta"]
    output_capabilities = ["text", "resource:file", "structured", "meta"]

    config_defaults = {
        "provider_id": "",
        "prompt": "",
        "images": "",
        "tier": "Gen-2",
        "use_original_alpha": "false",
        "seed": "",
        "geometry_file_format": "glb",
        "material": "PBR",
        "quality": "",
        "quality_override": "",
        "TAPose": "false",
        "bbox_width_y": "",
        "bbox_height_z": "",
        "bbox_length_x": "",
        "mesh_mode": "Quad",
        "addons": "",
        "preview_render": "false",
        "hd_texture": "false",
        "filename_prefix": "generated_model",
    }

    config_schema = {
        "provider_id": {
            "type": "string",
            "label": "provider_id",
            "description": "Only providers whose supportmode contains model_generation should be selected.",
        },
        "prompt": {
            "type": "text",
            "label": "prompt",
            "description": "Required for Text-to-3D. Optional for Image-to-3D.",
        },
        "images": {
            "type": "text",
            "label": "images",
            "description": "Optional JSON array or newline-separated image paths/URLs. Rodin accepts up to 5 images.",
        },
        "tier": {
            "type": "select",
            "label": "tier",
            "options": [
                {"value": "Gen-2", "label": "Gen-2"},
                {"value": "Regular", "label": "Regular"},
            ],
            "description": "Use Gen-2 for the Hyper3D Rodin Gen-2 generation API.",
        },
        "use_original_alpha": {
            "type": "boolean",
            "label": "use_original_alpha",
            "description": "Use original image transparency while processing image inputs.",
        },
        "seed": {
            "type": "number",
            "label": "seed",
            "min": 0,
            "max": 65535,
            "step": 1,
            "placeholder": "0-65535",
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
                {"value": "All", "label": "All"},
                {"value": "None", "label": "None"},
            ],
        },
        "quality": {
            "type": "select",
            "label": "quality",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "high", "label": "high"},
                {"value": "medium", "label": "medium"},
                {"value": "low", "label": "low"},
                {"value": "extra-low", "label": "extra-low"},
            ],
            "description": "Ignored by Rodin when quality_override is set.",
        },
        "quality_override": {
            "type": "number",
            "label": "quality_override",
            "min": 500,
            "max": 1000000,
            "step": 1,
            "description": "Raw supports 500-1000000. Quad supports 1000-200000.",
        },
        "TAPose": {
            "type": "boolean",
            "label": "TAPose",
            "description": "Ask Rodin to generate a T/A pose for human-like models.",
        },
        "bbox_width_y": {"type": "number", "label": "bbox_width_y", "step": 1},
        "bbox_height_z": {"type": "number", "label": "bbox_height_z", "step": 1},
        "bbox_length_x": {"type": "number", "label": "bbox_length_x", "step": 1},
        "mesh_mode": {
            "type": "select",
            "label": "mesh_mode",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "Raw", "label": "Raw"},
                {"value": "Quad", "label": "Quad"},
            ],
        },
        "addons": {
            "type": "select",
            "label": "addons",
            "options": [
                {"value": "", "label": "none"},
                {"value": "HighPack", "label": "HighPack"},
            ],
            "description": "HighPack requests 4K texture and higher face counts where supported.",
        },
        "preview_render": {"type": "boolean", "label": "preview_render"},
        "hd_texture": {"type": "boolean", "label": "hd_texture"},
        "filename_prefix": {
            "type": "string",
            "label": "filename_prefix",
            "description": "Prefix for downloaded result files.",
        },
    }

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        options = build_provider_options_for_support_modes(
            _SUPPORTED_PROVIDER_MODES,
            include_private=provider_options_include_private(context),
        )
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
        options = build_provider_options_for_support_modes(
            _SUPPORTED_PROVIDER_MODES,
            include_private=provider_options_include_private(context),
        )
        if options:
            config["provider_id"] = options[0]["value"]

    @staticmethod
    def _bbox_condition(ctx: dict) -> list[int]:
        values = [ctx.get("bbox_width_y"), ctx.get("bbox_height_z"), ctx.get("bbox_length_x")]
        if all(value in {None, ""} for value in values):
            return []
        if any(value in {None, ""} for value in values):
            raise ValueError("bbox_width_y, bbox_height_z, and bbox_length_x must be set together.")
        try:
            return [int(float(value)) for value in values]
        except Exception as exc:
            raise ValueError("Bounding box values must be integers.") from exc

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        node_id = str(ctx.get("node_instance_id") or ctx.get("node_id") or "model_generation").strip() or "model_generation"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node_dir = os.path.join(base_dir, "memories", graph_id, node_id)
        merged_ctx = merge_node_config_overlay(ctx, node_dir)

        provider_id = str(merged_ctx.get("provider_id") or "").strip()
        if not provider_id:
            raise ValueError("provider_id is required")

        prompt, images = resolve_model_generation_inputs(
            message,
            prompt=merged_ctx.get("prompt"),
            images=merged_ctx.get("images"),
        )

        memory_path = os.path.join(node_dir, f"{node_id}.md")
        agent = create_agent(provider_id, memory_file_path=memory_path)
        self._inject_configured_skills(agent, merged_ctx, node_id=node_id)
        if not hasattr(agent, "generate_3d_model"):
            raise ValueError(f"Provider '{provider_id}' does not support 3D model generation")

        result = agent.generate_3d_model(
            prompt=prompt,
            images=images,
            filename_prefix=str(merged_ctx.get("filename_prefix") or "generated_model").strip() or "generated_model",
            tier=merged_ctx.get("tier"),
            use_original_alpha=merged_ctx.get("use_original_alpha"),
            seed=merged_ctx.get("seed"),
            geometry_file_format=merged_ctx.get("geometry_file_format"),
            material=merged_ctx.get("material"),
            quality=merged_ctx.get("quality"),
            quality_override=merged_ctx.get("quality_override"),
            tapose=merged_ctx.get("TAPose"),
            bbox_condition=self._bbox_condition(merged_ctx),
            mesh_mode=merged_ctx.get("mesh_mode"),
            addons=merged_ctx.get("addons"),
            preview_render=merged_ctx.get("preview_render"),
            hd_texture=merged_ctx.get("hd_texture"),
        )
        output_message = build_generation_output_message(
            result,
            text_fields=("response",),
            resource_fields=(
                ResourceOutputField(
                    name="saved_files",
                    kind="file",
                    source="model_generation",
                    allow_list=True,
                ),
            ),
            structured=StructuredOutputSpec(
                base={"provider_id": provider_id},
                field_names=("task_uuid", "subscription_key", "status"),
                count_field="saved_files",
                count_name="file_count",
            ),
            json_fallback="when_only_structured",
        )
        return {
            "display": envelope_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
