import json
import os

from nodes.base_node import BaseNode
from src.config_loader import ConfigLoader
from src.message_protocol import build_resource_part, normalize_envelope
from src.providers import create_agent
from src.video_change_person_content import (
    normalize_public_base_url,
    resolve_video_change_person_inputs,
)


_SUPPORTED_PROVIDER_MODES = {
    "video_changeperson",
    "video_change_person",
}


class Node(BaseNode):
    name = "Video Change Person"
    description = "Replace the character in a reference video with a supplied portrait image using Wan Animate Mix."
    input_capabilities = [
        "resource:image",
        "resource:video",
        "resource:file",
        "resource:url",
        "structured",
        "meta",
    ]
    output_capabilities = [
        "text",
        "resource:video",
        "structured",
        "meta",
    ]

    config_defaults = {
        "provider_id": "",
        "image_path": "",
        "video_path": "",
        "mode": "wan-std",
        "watermark": "false",
        "check_image": "true",
        "filename_prefix": "generated_video_change_person",
        "public_base_url": "",
    }
    config_schema = {
        "provider_id": {
            "type": "string",
            "label": "provider_id",
            "description": "Only providers whose supportmode contains video_changePerson should be selected.",
        },
        "image_path": {
            "type": "string",
            "label": "image_path",
            "description": "Public image URL or local portrait image path. The node requires exactly one image input.",
        },
        "video_path": {
            "type": "string",
            "label": "video_path",
            "description": "Public video URL or local reference video path. The node requires exactly one video input.",
        },
        "mode": {
            "type": "select",
            "label": "mode",
            "options": [
                {"value": "wan-std", "label": "wan-std"},
                {"value": "wan-pro", "label": "wan-pro"},
            ],
            "description": "wan-std is faster and cheaper. wan-pro improves motion quality.",
        },
        "watermark": {
            "type": "boolean",
            "label": "watermark",
            "description": "Add the provider watermark to the output video.",
        },
        "check_image": {
            "type": "boolean",
            "label": "check_image",
            "description": "Enable provider-side image inspection before generation.",
        },
        "filename_prefix": {
            "type": "string",
            "label": "filename_prefix",
            "description": "Prefix for the downloaded generated video file.",
        },
        "public_base_url": {
            "type": "string",
            "label": "public_base_url",
            "description": "Required when image_path or video_path is a local file path. The node exposes local files through /api/files/raw.",
        },
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
                normalized_modes = (
                    {str(item or "").strip().lower() for item in modes}
                    if isinstance(modes, list)
                    else set()
                )
                if not normalized_modes.intersection(_SUPPORTED_PROVIDER_MODES):
                    continue
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

    def _resolve_public_base_url(self, explicit: object, provider_id: str) -> str:
        direct = normalize_public_base_url(explicit)
        if direct:
            return direct

        env_value = normalize_public_base_url(os.environ.get("AITOOLS_PUBLIC_BASE_URL"))
        if env_value:
            return env_value

        try:
            full_config = ConfigLoader().get_config()
        except Exception:
            full_config = {}
        if isinstance(full_config, dict):
            top_level = normalize_public_base_url(
                full_config.get("publicBaseUrl") or full_config.get("public_base_url")
            )
            if top_level:
                return top_level

        try:
            provider_config = ConfigLoader().get_provider_config(provider_id)
        except Exception:
            provider_config = {}
        if isinstance(provider_config, dict):
            provider_level = normalize_public_base_url(
                provider_config.get("publicBaseUrl") or provider_config.get("public_base_url")
            )
            if provider_level:
                return provider_level
        return ""

    def _build_output_message(self, response: object, *, provider_id: str, mode: str) -> dict:
        if not isinstance(response, dict):
            return normalize_envelope({"role": "assistant", "parts": [{"type": "text", "text": str(response or "")}]})

        parts: list[dict] = []
        response_text = str(response.get("response") or response.get("text") or "").strip()
        if response_text:
            parts.append({"type": "text", "text": response_text})

        video_path = str(response.get("video_path") or "").strip()
        if video_path:
            parts.append(build_resource_part(uri=video_path, kind="video", source="video_change_person"))

        meta = {"provider_id": provider_id, "mode": mode}
        for key in ("task_id", "video_url", "status", "request_id", "video_duration", "video_ratio"):
            value = response.get(key)
            if value is not None and value != "":
                meta[key] = value
        parts.append({"type": "structured", "data": meta})

        if len(parts) == 1 and parts[0].get("type") == "structured":
            parts.insert(0, {"type": "text", "text": json.dumps(response, ensure_ascii=False)})

        return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        node_id = str(ctx.get("node_instance_id") or ctx.get("node_id") or "video_change_person").strip() or "video_change_person"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"

        provider_id = str(ctx.get("provider_id") or "").strip()
        image_path = ctx.get("image_path")
        video_path = ctx.get("video_path")
        mode = str(ctx.get("mode") or "wan-std").strip() or "wan-std"
        watermark = ctx.get("watermark")
        check_image = ctx.get("check_image")
        filename_prefix = str(ctx.get("filename_prefix") or "generated_video_change_person").strip() or "generated_video_change_person"
        public_base_url = ctx.get("public_base_url")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node_dir = os.path.join(base_dir, "memories", graph_id, node_id)
        config_path = os.path.join(node_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as file_obj:
                    data = json.load(file_obj)
                if isinstance(data, dict):
                    provider_id = str(data.get("provider_id") or provider_id or "").strip()
                    image_path = data.get("image_path", image_path)
                    video_path = data.get("video_path", video_path)
                    mode = str(data.get("mode") or mode or "wan-std").strip() or "wan-std"
                    watermark = data.get("watermark", watermark)
                    check_image = data.get("check_image", check_image)
                    filename_prefix = str(data.get("filename_prefix") or filename_prefix or "generated_video_change_person").strip() or "generated_video_change_person"
                    if data.get("public_base_url") is not None:
                        public_base_url = data.get("public_base_url")
            except Exception:
                pass

        if not provider_id:
            raise ValueError("provider_id is required")

        resolved_public_base_url = self._resolve_public_base_url(public_base_url, provider_id)
        image_url, video_url = resolve_video_change_person_inputs(
            message,
            image_path=image_path,
            video_path=video_path,
            public_base_url=resolved_public_base_url,
        )

        memory_path = os.path.join(node_dir, f"{node_id}.md")
        agent = create_agent(provider_id, memory_file_path=memory_path)
        if not hasattr(agent, "generate_video_change_person"):
            raise ValueError(f"Provider '{provider_id}' does not support video change person")

        result = agent.generate_video_change_person(
            image_url=image_url,
            video_url=video_url,
            mode=mode,
            watermark=watermark,
            check_image=check_image,
            filename_prefix=filename_prefix,
        )
        output_message = self._build_output_message(result, provider_id=provider_id, mode=mode)
        return {
            "display": self._message_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
