from src.providers.agnes_image_generation import AgnesImageGeneration
from src.providers.agnes_video_generation import AgnesVideoGeneration
from src.providers.doubao_http_transport import DoubaoHttpTransport
from src.providers.image_generation_input import latest_image_generation_input
from src.providers.openai_agent import OpenAIAgent
from src.switch_utils import parse_switch_mode


class AgnesAgent(OpenAIAgent):
    """OpenAI-compatible Agnes chat with native Agnes media generation."""

    def _iter_service_targets(self) -> tuple[object, ...]:
        try:
            cached = object.__getattribute__(self, "_service_targets_cache")
        except AttributeError:
            cached = None
        if cached is None:
            openai_targets = OpenAIAgent._iter_service_targets(self)
            cached = (
                DoubaoHttpTransport(self),
                AgnesImageGeneration(self),
                AgnesVideoGeneration(self),
                *openai_targets,
            )
            object.__setattr__(self, "_service_targets_cache", cached)
        return cached

    @staticmethod
    def _latest_video_content(messages):
        if not isinstance(messages, list):
            return []
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            if isinstance(content, str):
                text = content.strip()
                return [{"type": "text", "text": text}] if text else []
            if isinstance(content, list):
                return [dict(item) for item in content if isinstance(item, dict)]
        return []

    def Send(
        self,
        tools=None,
        run_tools=True,
        mode="chat",
        web_search=None,
        thinking=None,
        reasoning_effort=None,
        reasoning_summary=None,
        stream=False,
        stream_handler=None,
        thinking_stream_handler=None,
        mode_options=None,
    ):
        normalized_mode = str(mode or "chat").strip().lower()
        self.config = self._read_provider_config_from_file()

        if normalized_mode == "image_generation":
            return self._send_image_generation(mode_options)
        if normalized_mode == "video_generation":
            return self._send_video_generation(mode_options, web_search=web_search)
        if normalized_mode not in {"chat", "imagechat"}:
            raise ValueError(
                "Agnes agent supports chat, imagechat, image_generation, and video_generation modes."
            )
        return super().Send(
            tools=tools,
            run_tools=run_tools,
            mode=normalized_mode,
            web_search=web_search,
            thinking=thinking,
            reasoning_effort=reasoning_effort,
            reasoning_summary=reasoning_summary,
            stream=stream,
            stream_handler=stream_handler,
            thinking_stream_handler=thinking_stream_handler,
        )

    def _send_image_generation(self, mode_options):
        options = dict(mode_options or {}) if isinstance(mode_options, dict) else {}
        prompt, references = latest_image_generation_input(
            self.messages, options.get("image_references")
        )
        if not prompt:
            return "Error: No prompt found for image generation."
        try:
            result = self.generate_image(
                prompt,
                filename_prefix=options.get("image_filename_prefix") or "generated_image",
                response_format=options.get("image_response_format") or "url",
                size=options.get("image_size"),
                image=references or None,
            )
            paths = [result] if isinstance(result, str) else list(result or [])
            if not paths:
                return "Image generation returned no files."
            return {
                "response": f"Image generated successfully: {', '.join(paths)}",
                "image_path": paths[0] if len(paths) == 1 else paths,
            }
        except Exception as exc:
            return f"Image generation failed: {exc}"

    def _send_video_generation(self, mode_options, *, web_search):
        options = dict(mode_options or {}) if isinstance(mode_options, dict) else {}
        content = self._latest_video_content(self.messages)
        if not content:
            return "Error: No content found for video generation."
        try:
            tools = (
                [{"type": "web_search"}]
                if parse_switch_mode(web_search, default="disabled") == "enabled"
                else None
            )
            return self.generate_video(
                content,
                filename_prefix=options.get("video_filename_prefix") or "generated_video",
                resolution=options.get("video_resolution"),
                ratio=options.get("video_ratio"),
                duration=options.get("video_duration"),
                frames=options.get("video_frames"),
                seed=options.get("video_seed"),
                tools=tools,
            )
        except Exception as exc:
            return f"Video generation failed: {exc}"
