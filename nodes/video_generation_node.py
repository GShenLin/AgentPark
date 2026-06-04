import json
import os

from nodes.base_node import BaseNode
from src.config_loader import ConfigLoader
from src.message_protocol import build_resource_part, normalize_envelope
from src.providers import create_agent
from src.video_generation_content import (
    build_doubao_video_generation_content,
    normalize_public_base_url,
)


class Node(BaseNode):
    name = "Video Generation"
    description = "Generate video from text, image, video, and audio references."
    input_capabilities = [
        "text",
        "resource:image",
        "resource:video",
        "resource:audio",
        "resource:file",
        "resource:url",
        "structured",
        "meta",
    ]
    output_capabilities = [
        "text",
        "resource:image",
        "resource:video",
        "structured",
        "meta",
    ]
    config_defaults = {
        "provider_id": "",
        "prompt": "",
        "first_frame_path": "",
        "last_frame_path": "",
        "reference_images": "",
        "reference_videos": "",
        "reference_audios": "",
        "resolution": "",
        "ratio": "",
        "duration": "",
        "seed": "",
        "generate_audio": "true",
        "watermark": "true",
        "return_last_frame": "false",
        "callback_url": "",
        "service_tier": "",
        "execution_expires_after": "",
        "safety_identifier": "",
        "web_search": "disabled",
        "filename_prefix": "generated_video",
        "public_base_url": "",
    }
    config_schema = {
        "provider_id": {"type": "string", "label": "provider_id"},
        "prompt": {
            "type": "text",
            "label": "prompt",
            "description": "Used only when the input message does not provide text.",
        },
        "first_frame_path": {
            "type": "string",
            "label": "first_frame_path",
            "description": "Local file path, asset:// URI, or remote image URL for the first frame.",
        },
        "last_frame_path": {
            "type": "string",
            "label": "last_frame_path",
            "description": "Local file path, asset:// URI, or remote image URL for the last frame.",
        },
        "reference_images": {
            "type": "text",
            "label": "reference_images",
            "description": "JSON array or newline-separated list of local paths, asset:// URIs, or image URLs.",
        },
        "reference_videos": {
            "type": "text",
            "label": "reference_videos",
            "description": "JSON array or newline-separated list of asset:// URIs or public video URLs.",
        },
        "reference_audios": {
            "type": "text",
            "label": "reference_audios",
            "description": "JSON array or newline-separated list of local paths, asset:// URIs, or audio URLs.",
        },
        "resolution": {
            "type": "select",
            "label": "resolution",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "480p", "label": "480p"},
                {"value": "720p", "label": "720p"},
            ],
            "description": "Seedance 2.0 supports 480p and 720p.",
        },
        "ratio": {
            "type": "select",
            "label": "ratio",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "16:9", "label": "16:9"},
                {"value": "4:3", "label": "4:3"},
                {"value": "1:1", "label": "1:1"},
                {"value": "3:4", "label": "3:4"},
                {"value": "9:16", "label": "9:16"},
                {"value": "21:9", "label": "21:9"},
                {"value": "adaptive", "label": "adaptive"},
            ],
            "description": "Supported ratios from the official API.",
        },
        "duration": {
            "type": "select",
            "label": "duration",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "-1", "label": "auto (-1)"},
                {"value": "4", "label": "4 s"},
                {"value": "5", "label": "5 s"},
                {"value": "6", "label": "6 s"},
                {"value": "7", "label": "7 s"},
                {"value": "8", "label": "8 s"},
                {"value": "9", "label": "9 s"},
                {"value": "10", "label": "10 s"},
                {"value": "11", "label": "11 s"},
                {"value": "12", "label": "12 s"},
                {"value": "13", "label": "13 s"},
                {"value": "14", "label": "14 s"},
                {"value": "15", "label": "15 s"},
            ],
            "description": "Seedance 2.0 supports 4-15 seconds, or -1 for automatic duration.",
        },
        "seed": {
            "type": "number",
            "label": "seed",
            "min": -1,
            "step": 1,
            "placeholder": "-1 or 0..4294967295",
            "description": "Use -1 for random seed. Otherwise enter an integer from 0 to 4294967295.",
        },
        "generate_audio": {
            "type": "boolean",
            "label": "generate_audio",
            "description": "Generate an audio track when the model supports it.",
        },
        "watermark": {
            "type": "boolean",
            "label": "watermark",
            "description": "Add the provider watermark to the generated video.",
        },
        "return_last_frame": {
            "type": "boolean",
            "label": "return_last_frame",
            "description": "Return the generated last frame URL in the node output metadata.",
        },
        "callback_url": {
            "type": "string",
            "label": "callback_url",
            "description": "Optional provider callback URL.",
        },
        "service_tier": {
            "type": "select",
            "label": "service_tier",
            "options": [
                {"value": "", "label": "provider default"},
                {"value": "default", "label": "default"},
            ],
            "description": "Seedance 2.0 currently supports the default service tier only.",
        },
        "execution_expires_after": {
            "type": "number",
            "label": "execution_expires_after",
            "min": 3600,
            "max": 259200,
            "step": 1,
            "placeholder": "3600-259200",
            "description": "Allowed range is 3600 to 259200 seconds.",
        },
        "safety_identifier": {
            "type": "string",
            "label": "safety_identifier",
            "description": "Optional identifier used for provider-side safety auditing.",
        },
        "web_search": {"type": "string", "label": "web_search"},
        "filename_prefix": {"type": "string", "label": "filename_prefix"},
        "public_base_url": {
            "type": "string",
            "label": "public_base_url",
            "description": "Public base URL used only when local video references must be exposed as URLs.",
        },
    }

    @staticmethod
    def _normalize_switch(value: object, default: str = "disabled") -> str:
        if isinstance(value, bool):
            return "enabled" if value else "disabled"
        text = str(value or "").strip().lower()
        if text in {"enabled", "enable", "on", "true", "1", "yes"}:
            return "enabled"
        if text in {"disabled", "disable", "off", "false", "0", "no"}:
            return "disabled"
        return default

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

    def _build_output_message(self, response: object) -> dict:
        if isinstance(response, dict):
            parts: list[dict] = []
            response_text = str(response.get("response") or response.get("text") or "").strip()
            if response_text:
                parts.append({"type": "text", "text": response_text})

            video_path = response.get("video_path")
            if isinstance(video_path, str) and video_path.strip():
                parts.append(build_resource_part(uri=video_path.strip(), kind="video", source="video_generation"))
            elif isinstance(video_path, list):
                for item in video_path:
                    uri = str(item or "").strip()
                    if uri:
                        parts.append(build_resource_part(uri=uri, kind="video", source="video_generation"))

            last_frame_url = response.get("last_frame_url")
            if isinstance(last_frame_url, str) and last_frame_url.strip():
                parts.append(build_resource_part(uri=last_frame_url.strip(), kind="image", source="video_generation"))

            meta = {}
            for key in ("task_id", "video_url", "last_frame_url", "status"):
                value = response.get(key)
                if value is not None and value != "":
                    meta[key] = value
            if meta:
                parts.append({"type": "structured", "data": meta})

            if not parts:
                parts.append({"type": "text", "text": json.dumps(response, ensure_ascii=False)})
            return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

        return normalize_envelope({"role": "assistant", "parts": [{"type": "text", "text": str(response or "")}]})

    @staticmethod
    def _parse_resource_list(value: object) -> list[str]:
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        text = str(value or "").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [line.strip() for line in text.splitlines() if line.strip()]

    def _merge_configured_resources(
        self,
        message: object,
        *,
        first_frame_path: object = "",
        last_frame_path: object = "",
        reference_images: object = "",
        reference_videos: object = "",
        reference_audios: object = "",
    ) -> dict:
        envelope = normalize_envelope(message, default_role="user")
        parts = list(envelope.get("parts") or [])

        first_frame = str(first_frame_path or "").strip()
        if first_frame:
            parts.append(
                build_resource_part(
                    uri=first_frame,
                    kind="image",
                    source="video_generation_node",
                    metadata={"role": "first_frame"},
                )
            )

        last_frame = str(last_frame_path or "").strip()
        if last_frame:
            parts.append(
                build_resource_part(
                    uri=last_frame,
                    kind="image",
                    source="video_generation_node",
                    metadata={"role": "last_frame"},
                )
            )

        for uri in self._parse_resource_list(reference_images):
            parts.append(
                build_resource_part(
                    uri=uri,
                    kind="image",
                    source="video_generation_node",
                    metadata={"role": "reference_image"},
                )
            )

        for uri in self._parse_resource_list(reference_videos):
            parts.append(
                build_resource_part(
                    uri=uri,
                    kind="video",
                    source="video_generation_node",
                    metadata={"role": "reference_video"},
                )
            )

        for uri in self._parse_resource_list(reference_audios):
            parts.append(
                build_resource_part(
                    uri=uri,
                    kind="audio",
                    source="video_generation_node",
                    metadata={"role": "reference_audio"},
                )
            )

        return normalize_envelope({"role": envelope.get("role") or "user", "parts": parts}, default_role="user")

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        node_id = str(ctx.get("node_instance_id") or ctx.get("node_id") or "video_generation").strip() or "video_generation"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"

        provider_id = str(ctx.get("provider_id") or "").strip()
        prompt = str(ctx.get("prompt") or "").strip()
        first_frame_path = ctx.get("first_frame_path")
        last_frame_path = ctx.get("last_frame_path")
        reference_images = ctx.get("reference_images")
        reference_videos = ctx.get("reference_videos")
        reference_audios = ctx.get("reference_audios")
        resolution = ctx.get("resolution")
        ratio = ctx.get("ratio")
        duration = ctx.get("duration")
        frames = ctx.get("frames")
        seed = ctx.get("seed")
        camera_fixed = ctx.get("camera_fixed")
        generate_audio = ctx.get("generate_audio")
        watermark = ctx.get("watermark")
        return_last_frame = ctx.get("return_last_frame")
        callback_url = ctx.get("callback_url")
        service_tier = ctx.get("service_tier")
        execution_expires_after = ctx.get("execution_expires_after")
        safety_identifier = ctx.get("safety_identifier")
        web_search = ctx.get("web_search")
        filename_prefix = str(ctx.get("filename_prefix") or "").strip()
        public_base_url = ctx.get("public_base_url")

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        node_dir = os.path.join(base_dir, "memories", graph_id, node_id)
        config_path = os.path.join(node_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    provider_id = str(data.get("provider_id") or provider_id or "").strip()
                    prompt = str(data.get("prompt") or prompt or "").strip()
                    first_frame_path = data.get("first_frame_path", first_frame_path)
                    last_frame_path = data.get("last_frame_path", last_frame_path)
                    reference_images = data.get("reference_images", reference_images)
                    reference_videos = data.get("reference_videos", reference_videos)
                    reference_audios = data.get("reference_audios", reference_audios)
                    resolution = data.get("resolution", resolution)
                    ratio = data.get("ratio", ratio)
                    duration = data.get("duration", duration)
                    seed = data.get("seed", seed)
                    generate_audio = data.get("generate_audio", generate_audio)
                    watermark = data.get("watermark", watermark)
                    return_last_frame = data.get("return_last_frame", return_last_frame)
                    callback_url = data.get("callback_url", callback_url)
                    service_tier = data.get("service_tier", service_tier)
                    execution_expires_after = data.get("execution_expires_after", execution_expires_after)
                    safety_identifier = data.get("safety_identifier", safety_identifier)
                    web_search = data.get("web_search", web_search)
                    filename_prefix = str(data.get("filename_prefix") or filename_prefix or "").strip()
                    if data.get("public_base_url") is not None:
                        public_base_url = data.get("public_base_url")
            except Exception:
                pass

        if not provider_id:
            raise ValueError("provider_id is required")

        merged_message = self._merge_configured_resources(
            message,
            first_frame_path=first_frame_path,
            last_frame_path=last_frame_path,
            reference_images=reference_images,
            reference_videos=reference_videos,
            reference_audios=reference_audios,
        )
        resolved_public_base_url = self._resolve_public_base_url(public_base_url, provider_id)
        content = build_doubao_video_generation_content(
            merged_message,
            public_base_url=resolved_public_base_url,
            fallback_prompt=prompt,
        )

        memory_path = os.path.join(node_dir, f"{node_id}.md")
        agent = create_agent(provider_id, memory_file_path=memory_path)
        if not hasattr(agent, "generate_video"):
            raise ValueError(f"Provider '{provider_id}' does not support video generation")

        tools = [{"type": "web_search"}] if self._normalize_switch(web_search, default="disabled") == "enabled" else None
        result = agent.generate_video(
            content,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            frames=frames,
            seed=seed,
            camera_fixed=camera_fixed,
            generate_audio=generate_audio,
            watermark=watermark,
            return_last_frame=return_last_frame,
            callback_url=callback_url,
            service_tier=service_tier,
            execution_expires_after=execution_expires_after,
            safety_identifier=safety_identifier,
            filename_prefix=filename_prefix or "generated_video",
            tools=tools,
        )

        output_message = self._build_output_message(result)
        return {
            "display": self._message_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
