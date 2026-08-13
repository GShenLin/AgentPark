from __future__ import annotations

import os
import re
from urllib.parse import unquote, urlsplit
from urllib.request import url2pathname

from nodes.base_node import BaseNode
from src.generation_output import ResourceOutputField, StructuredOutputSpec, build_generation_output_message
from src.image_matting import MagicWandMattingConfig, remove_connected_background
from src.message_protocol import MetaPart, ResourcePart, normalize_message_envelope
from src.node_config_overlay import merge_node_config_overlay
from src.provider_options import build_provider_options_for_support_modes, provider_options_include_private
from src.providers import create_agent
from src.providers.provider_errors import ProviderInputError


_SUPPORTED_PROVIDER_MODES = {"image_matting"}
_METHOD_MAGIC_WAND = "magic_wand"
_METHOD_AI_MATTING = "ai_matting"
_SUPPORTED_METHODS = {_METHOD_MAGIC_WAND, _METHOD_AI_MATTING}


class Node(BaseNode):
    support_modes = tuple(sorted(_SUPPORTED_PROVIDER_MODES))
    name = "Image Matting"
    description = "Remove a connected background or use AI matting, then return a validated transparent PNG."
    input_capabilities = ["resource:image", "meta"]
    output_capabilities = ["resource:image", "structured", "meta"]

    config_defaults = {
        "method": _METHOD_MAGIC_WAND,
        "provider_id": "",
        "background_color": "",
        "tolerance": 1,
        "edge_softness": 0,
        "feather_px": 0.0,
        "filename_prefix": "matted_image",
    }
    config_schema = {
        "method": {
            "type": "select",
            "label": "Method",
            "description": "Magic Wand Alpha deterministically removes matching background connected to the image boundary.",
            "options": [
                {"value": _METHOD_MAGIC_WAND, "label": "Magic Wand Alpha (Default)"},
                {"value": _METHOD_AI_MATTING, "label": "AI Matting"},
            ],
        },
        "provider_id": {
            "type": "select",
            "label": "Matting Provider",
            "options": [],
            "description": "Only providers whose supportmode contains image_matting can be selected.",
            "visible_when": {"field": "method", "equals": _METHOD_AI_MATTING},
        },
        "background_color": {
            "type": "color",
            "label": "Background Color",
            "description": "Auto uses all four corner colors. Pick a color to use one explicit #RRGGBB background sample.",
            "default_color": "#FFFFFF",
            "auto_label": "Auto",
            "visible_when": {"field": "method", "equals": _METHOD_MAGIC_WAND},
        },
        "tolerance": {
            "type": "number",
            "label": "Tolerance",
            "description": "Maximum per-channel RGB distance from any active background color sample.",
            "min": 0,
            "max": 255,
            "step": 1,
            "visible_when": {"field": "method", "equals": _METHOD_MAGIC_WAND},
        },
        "edge_softness": {
            "type": "number",
            "label": "Edge Softness",
            "description": "Color-distance width used to reconstruct anti-aliased edge pixels as continuous Alpha and remove background color spill.",
            "min": 0,
            "max": 255,
            "step": 1,
            "visible_when": {"field": "method", "equals": _METHOD_MAGIC_WAND},
        },
        "feather_px": {
            "type": "number",
            "label": "Feather (px)",
            "description": "Optional inward Gaussian softening applied after edge Alpha reconstruction.",
            "min": 0,
            "max": 32,
            "step": 0.5,
            "visible_when": {"field": "method", "equals": _METHOD_MAGIC_WAND},
        },
        "filename_prefix": {
            "type": "string",
            "label": "Filename Prefix",
            "description": "Filename prefix for the transparent PNG saved in this node's output folder.",
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
            provider_schema["options"] = options
            schema["provider_id"] = provider_schema
        return schema

    def on_create(self, config: dict, context: dict | None = None) -> None:
        super().on_create(config, context)
        if (
            not isinstance(config, dict)
            or config.get("method") != _METHOD_AI_MATTING
            or str(config.get("provider_id") or "").strip()
        ):
            return
        options = build_provider_options_for_support_modes(
            _SUPPORTED_PROVIDER_MODES,
            include_private=provider_options_include_private(context),
        )
        if options:
            config["provider_id"] = options[0]["value"]

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        memory_path = self._resolve_memory_path(ctx)
        node_dir = os.path.dirname(memory_path)
        merged_ctx = merge_node_config_overlay(ctx, node_dir)

        method = str(merged_ctx.get("method") or _METHOD_MAGIC_WAND).strip()
        if method not in _SUPPORTED_METHODS:
            raise ProviderInputError(
                f"method must be one of: {', '.join(sorted(_SUPPORTED_METHODS))}."
            )
        image_path = self._extract_single_local_image(message)
        output_dir = os.path.join(node_dir, "output")
        filename_prefix = str(
            merged_ctx.get("filename_prefix") or "matted_image"
        ).strip()

        if method == _METHOD_MAGIC_WAND:
            try:
                magic_wand_config = MagicWandMattingConfig.from_values(
                    tolerance=merged_ctx.get("tolerance", 1),
                    edge_softness=merged_ctx.get("edge_softness", 0),
                    feather_px=merged_ctx.get("feather_px", 0.0),
                    background_color=merged_ctx.get("background_color", ""),
                )
                result = remove_connected_background(
                    image_path=image_path,
                    output_dir=output_dir,
                    filename_prefix=filename_prefix,
                    config=magic_wand_config,
                )
            except (ValueError, RuntimeError) as exc:
                raise ProviderInputError(str(exc)) from exc
            structured_base = {"method": _METHOD_MAGIC_WAND}
        else:
            provider_id = str(merged_ctx.get("provider_id") or "").strip()
            if not provider_id:
                raise ProviderInputError("provider_id is required when method is ai_matting.")
            agent = create_agent(provider_id, memory_file_path=memory_path)
            matte_image = getattr(agent, "matte_image", None)
            if not callable(matte_image):
                raise ProviderInputError(
                    f"Provider '{provider_id}' does not support image matting."
                )
            result = matte_image(
                image_path=image_path,
                output_dir=output_dir,
                filename_prefix=filename_prefix,
            )
            structured_base = {
                "method": _METHOD_AI_MATTING,
                "provider_id": provider_id,
            }
        output_message = build_generation_output_message(
            result,
            text_fields=(),
            resource_fields=(
                ResourceOutputField(
                    name="image_path",
                    kind="image",
                    source="image_matting",
                ),
            ),
            structured=StructuredOutputSpec(
                base=structured_base,
                field_names=(
                    "status",
                    "model",
                    "model_revision",
                    "background_mode",
                    "background_color",
                    "background_colors",
                    "tolerance",
                    "edge_softness",
                    "feather_px",
                    "soft_edge_pixels",
                    "width",
                    "height",
                    "alpha_min",
                    "alpha_max",
                    "background_pixels",
                    "foreground_pixels",
                    "cuda_peak_memory_allocated_bytes",
                ),
            ),
        )
        return {
            "display_message": output_message,
            "routes": [{"output_index": 0, "payload": output_message}],
        }

    @staticmethod
    def _extract_single_local_image(message: object) -> str:
        envelope = normalize_message_envelope(message, default_role="user")
        images: list[str] = []
        for part in envelope.parts:
            if isinstance(part, MetaPart):
                continue
            if not isinstance(part, ResourcePart):
                raise ProviderInputError(
                    "Image Matting accepts exactly one resource:image part; text and structured input are not supported."
                )
            kind = str(part.resource.get("kind") or "").strip().lower()
            uri = str(part.resource.get("uri") or "").strip()
            if kind != "image" or not uri:
                raise ProviderInputError(
                    "Image Matting accepts exactly one non-empty resource:image part."
                )
            images.append(uri)
        if len(images) != 1:
            raise ProviderInputError(
                f"Image Matting requires exactly one resource:image part, received {len(images)}."
            )
        return Node._local_path_from_uri(images[0])

    @staticmethod
    def _local_path_from_uri(uri: str) -> str:
        if os.name == "nt" and re.match(r"^[a-zA-Z]:[\\/]", uri):
            resolved = os.path.abspath(uri)
            if not os.path.isfile(resolved):
                raise ProviderInputError(f"Input image does not exist: {resolved}")
            return resolved
        parsed = urlsplit(uri)
        if parsed.scheme and parsed.scheme.lower() != "file":
            raise ProviderInputError("Image Matting currently accepts local image files only.")
        if parsed.scheme.lower() == "file":
            if parsed.netloc not in {"", "localhost"}:
                raise ProviderInputError("Image Matting does not accept remote file URIs.")
            path = url2pathname(unquote(parsed.path))
        else:
            path = uri
        resolved = os.path.abspath(path)
        if not os.path.isfile(resolved):
            raise ProviderInputError(f"Input image does not exist: {resolved}")
        return resolved
