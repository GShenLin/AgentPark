import os

from nodes.base_node import BaseNode
from src.media_resource_utils import parse_resource_list
from src.message_protocol import build_resource_part, envelope_text, normalize_envelope
from src.provider_options import build_provider_options_for_support_modes
from src.providers import create_agent
from src.value_parsing import parse_optional_bool_value


_SUPPORTED_PROVIDER_MODES = {"image_generation"}


class Node(BaseNode):
    name = "Image Generation"
    description = "Generate images from a prompt and optional image references."
    input_capabilities = ["text", "resource:image", "resource:file", "resource:url", "structured", "meta"]
    output_capabilities = ["text", "resource:image", "structured", "meta"]

    config_defaults = {
        "provider_id": "",
        "prompt": "",
        "reference_images": "",
        "aspect_ratio": "",
        "image_size": "",
        "response_format": "url",
        "watermark": "false",
        "filename_prefix": "generated_image",
    }

    config_schema = {
        "provider_id": {
            "type": "string",
            "label": "provider_id",
            "description": "Only providers whose supportmode contains image_generation should be selected.",
        },
        "prompt": {
            "type": "text",
            "label": "prompt",
            "description": "Used when the input message does not provide text.",
        },
        "reference_images": {
            "type": "text",
            "label": "reference_images",
            "description": "Optional JSON array or newline-separated list of local image paths, data URLs, or remote image URLs.",
        },
        "aspect_ratio": {
            "type": "select",
            "label": "aspect_ratio",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "1:1", "label": "1:1"},
                {"value": "2:3", "label": "2:3"},
                {"value": "3:2", "label": "3:2"},
                {"value": "3:4", "label": "3:4"},
                {"value": "4:3", "label": "4:3"},
                {"value": "4:5", "label": "4:5"},
                {"value": "5:4", "label": "5:4"},
                {"value": "9:16", "label": "9:16"},
                {"value": "16:9", "label": "16:9"},
                {"value": "21:9", "label": "21:9"},
            ],
            "description": "Gemini image generation supports fixed aspect ratio choices; unsupported providers may reject unsupported values.",
        },
        "image_size": {
            "type": "select",
            "label": "image_size",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "1K", "label": "1K"},
                {"value": "2K", "label": "2K"},
                {"value": "4K", "label": "4K"},
            ],
            "description": "Resolution/image size option. Gemini image models document 1K/2K/4K options depending on model support.",
        },
        "response_format": {
            "type": "select",
            "label": "response_format",
            "options": [
                {"value": "url", "label": "url"},
                {"value": "b64_json", "label": "b64_json"},
            ],
            "description": "Used by OpenAI/Doubao-compatible image generation endpoints.",
        },
        "watermark": {
            "type": "boolean",
            "label": "watermark",
            "description": "Ask the provider to add a watermark when supported.",
        },
        "filename_prefix": {
            "type": "string",
            "label": "filename_prefix",
            "description": "Prefix for saved generated image files.",
        },
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

    def _extract_prompt_and_images(self, message: object, configured_prompt: object, configured_images: object) -> tuple[str, list[str]]:
        envelope = normalize_envelope(message, default_role="user")
        parts = envelope.get("parts") if isinstance(envelope, dict) else []
        text_parts: list[str] = []
        images = parse_resource_list(configured_images)

        for part in parts if isinstance(parts, list) else []:
            if not isinstance(part, dict):
                continue
            part_type = str(part.get("type") or "").strip().lower()
            if part_type == "text":
                text = str(part.get("text") or "").strip()
                if text:
                    text_parts.append(text)
                continue
            if part_type != "resource":
                continue
            res = part.get("resource")
            if not isinstance(res, dict):
                continue
            kind = str(res.get("kind") or "").strip().lower()
            uri = str(res.get("uri") or "").strip()
            if kind == "image" and uri:
                images.append(uri)

        prompt = "\n".join(text_parts).strip() or str(configured_prompt or "").strip()
        return prompt, images

    def _build_output_message(self, result: object, *, provider_id: str, aspect_ratio: str, image_size: str) -> dict:
        image_paths: list[str] = []
        text_parts: list[str] = []

        if isinstance(result, dict):
            image_value = result.get("image_path") or result.get("saved_files")
            response_text = str(result.get("response") or result.get("text") or "").strip()
            if response_text:
                text_parts.append(response_text)
        else:
            image_value = result

        if isinstance(image_value, str) and image_value.strip():
            image_paths.append(image_value.strip())
        elif isinstance(image_value, list):
            image_paths.extend(str(item).strip() for item in image_value if str(item).strip())

        parts: list[dict] = []
        for text in text_parts:
            parts.append({"type": "text", "text": text})
        for path in image_paths:
            parts.append(build_resource_part(uri=path, kind="image", source="image_generation"))

        meta = {"provider_id": provider_id}
        if aspect_ratio:
            meta["aspect_ratio"] = aspect_ratio
        if image_size:
            meta["image_size"] = image_size
        if image_paths:
            meta["image_count"] = len(image_paths)
        parts.append({"type": "structured", "data": meta})

        if not image_paths and not text_parts:
            parts.insert(0, {"type": "text", "text": json.dumps(result, ensure_ascii=False)})

        return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        node_id = str(ctx.get("node_instance_id") or ctx.get("node_id") or "image_generation").strip() or "image_generation"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"

        provider_id = str(ctx.get("provider_id") or "").strip()
        prompt, reference_images = self._extract_prompt_and_images(
            message,
            ctx.get("prompt"),
            ctx.get("reference_images"),
        )
        aspect_ratio = str(ctx.get("aspect_ratio") or "").strip()
        image_size = str(ctx.get("image_size") or "").strip()
        response_format = str(ctx.get("response_format") or "url").strip() or "url"
        filename_prefix = str(ctx.get("filename_prefix") or "generated_image").strip() or "generated_image"
        watermark = parse_optional_bool_value("watermark", ctx.get("watermark"))
        if watermark is None:
            watermark = False

        if not provider_id:
            raise ValueError("provider_id is required")
        if not prompt:
            raise ValueError("prompt is required")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node_dir = os.path.join(base_dir, "memories", graph_id, node_id)
        memory_path = os.path.join(node_dir, f"{node_id}.md")
        agent = create_agent(provider_id, memory_file_path=memory_path)
        self._inject_configured_skills(agent, ctx, node_id=node_id)
        if not hasattr(agent, "generate_image"):
            raise ValueError(f"Provider '{provider_id}' does not support image generation")

        result = agent.generate_image(
            prompt=prompt,
            filename_prefix=filename_prefix,
            size=image_size or None,
            image_size=image_size or None,
            aspect_ratio=aspect_ratio or None,
            response_format=response_format,
            watermark=watermark,
            image=reference_images or None,
        )
        output_message = self._build_output_message(
            result,
            provider_id=provider_id,
            aspect_ratio=aspect_ratio,
            image_size=image_size,
        )
        return {
            "display": envelope_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
