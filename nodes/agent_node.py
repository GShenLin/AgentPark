import json
import os
import time
import base64
from typing import Callable

from nodes.agent_stream_runtime import AgentStreamRuntime
from nodes.agent_tool_loader import load_configured_tools, normalize_tool_names
from nodes.base_node import BaseNode
from nodes.agent_working_path_context import prepend_working_path_context
from src.config_loader import ConfigLoader
from src.message_protocol import build_resource_part, build_text_envelope, normalize_envelope
from src.providers import create_agent
from src.video_generation_content import build_doubao_video_generation_content, normalize_public_base_url


class Node(BaseNode):
    name = "Agent"
    description = "Agent 节点"
    input_capabilities = [
        "text",
        "resource:image",
        "resource:video",
        "resource:audio",
        "resource:doc",
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
        "tool_call",
        "meta",
    ]

    config_defaults = {
        "provider_id": "",
        "system_prompt": "",
        "mode": "chat",
        "tools": [],
        "web_search": "disabled",
        "thinking": "enabled",
    }
    config_schema = {
        "provider_id": {"type": "text", "label": "provider_id"},
        "system_prompt": {"type": "text", "label": "system_prompt"},
        "mode": {"type": "text", "label": "mode"},
        "tools": {"type": "json", "label": "tools"},
        "web_search": {"type": "text", "label": "web_search"},
        "thinking": {"type": "text", "label": "thinking"},
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

    @staticmethod
    def _to_local_path(uri: object) -> str:
        raw = str(uri or "").strip()
        if not raw:
            return ""
        if raw.startswith("file://"):
            return raw[7:]
        return raw

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

    def _build_user_content(self, provider_id: str, mode: str, message: object, public_base_url: object = ""):
        envelope = normalize_envelope(message, default_role="user")
        parts = envelope.get("parts") if isinstance(envelope, dict) else []
        text_parts: list[str] = []
        image_uris: list[str] = []
        other_resources: list[dict] = []

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
            uri = str(res.get("uri") or "").strip()
            kind = str(res.get("kind") or "").strip().lower()
            if kind == "image" and uri:
                image_uris.append(uri)
            else:
                other_resources.append(res)

        if str(mode or "").strip().lower() == "video_generation" and "doubao" in str(provider_id or "").strip().lower():
            return build_doubao_video_generation_content(
                envelope,
                public_base_url=public_base_url,
            )

        if other_resources:
            text_parts.extend(
                [f"[{str(item.get('kind') or 'file')}] {str(item.get('uri') or '').strip()}" for item in other_resources]
            )
        merged_text = "\n".join([item for item in text_parts if item]).strip()
        provider = str(provider_id or "").strip().lower()

        if not image_uris:
            return merged_text

        # Gemini supports image via {"type":"image","path":...,"text":...}
        if "gemini" in provider:
            local_path = self._to_local_path(image_uris[0])
            if local_path and os.path.exists(local_path):
                return {"type": "image", "path": local_path, "text": merged_text}
            return merged_text + f"\n[image] {image_uris[0]}"

        # Doubao/OpenAI-compatible payload with image_url parts.
        content_parts = []
        if merged_text:
            content_parts.append({"type": "text", "text": merged_text})
        for uri in image_uris:
            image_url = uri
            local_path = self._to_local_path(uri)
            if local_path and os.path.exists(local_path):
                try:
                    with open(local_path, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode("utf-8")
                    image_url = f"data:image/png;base64,{encoded}"
                except Exception:
                    image_url = uri
            content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
        return content_parts

    def _build_output_message(self, response: object) -> dict:
        if isinstance(response, dict):
            parts: list[dict] = []
            response_text = str(response.get("response") or response.get("text") or "").strip()
            if response_text:
                parts.append({"type": "text", "text": response_text})

            image_path = response.get("image_path")
            if isinstance(image_path, str) and image_path.strip():
                parts.append(build_resource_part(uri=image_path.strip(), kind="image", source="agent"))
            elif isinstance(image_path, list):
                for item in image_path:
                    uri = str(item or "").strip()
                    if uri:
                        parts.append(build_resource_part(uri=uri, kind="image", source="agent"))

            video_path = response.get("video_path")
            if isinstance(video_path, str) and video_path.strip():
                parts.append(build_resource_part(uri=video_path.strip(), kind="video", source="agent"))
            elif isinstance(video_path, list):
                for item in video_path:
                    uri = str(item or "").strip()
                    if uri:
                        parts.append(build_resource_part(uri=uri, kind="video", source="agent"))

            if not parts:
                parts.append({"type": "text", "text": json.dumps(response, ensure_ascii=False)})
            return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

        text = "" if response is None else str(response)
        return build_text_envelope(text, role="assistant")

    @staticmethod
    def _resolve_stream_callback(context: dict | None) -> Callable[[dict], None] | None:
        if not isinstance(context, dict):
            return None
        callback = context.get("stream_callback")
        if callable(callback):
            return callback
        return None

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        agent_id = str(ctx.get("node_instance_id") or ctx.get("agent_id") or "").strip() or "agent"
        graph_id = str(ctx.get("graph_id") or "default").strip() or "default"
        provider_id = str(ctx.get("provider_id") or "").strip()
        system_prompt = ctx.get("system_prompt")
        mode = str(ctx.get("mode") or "chat").strip() or "chat"
        web_search = ctx.get("web_search")
        thinking = ctx.get("thinking")
        public_base_url = ctx.get("public_base_url")
        working_path = str(ctx.get("working_path") or "").strip()
        ctx_tools = ctx.get("tools")
        tool_names = normalize_tool_names(ctx_tools)

        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        agent_dir = os.path.join(base_dir, "memories", graph_id, agent_id)
        config_path = os.path.join(agent_dir, "config.json")
        if os.path.exists(config_path):
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    provider_id = str(data.get("provider_id") or provider_id or "").strip()
                    if data.get("system_prompt") is not None:
                        system_prompt = data.get("system_prompt")
                    if data.get("mode"):
                        mode = str(data.get("mode"))
                    if "web_search" in data:
                        web_search = data.get("web_search")
                    if "thinking" in data:
                        thinking = data.get("thinking")
                    if data.get("public_base_url") is not None:
                        public_base_url = data.get("public_base_url")
                    if data.get("working_path") is not None:
                        working_path = str(data.get("working_path") or "").strip()
                    cfg_tools = data.get("tools")
                    tool_names.extend(normalize_tool_names(cfg_tools))
            except Exception:
                pass

        if not provider_id:
            raise ValueError("provider_id is required")

        memory_path = os.path.join(agent_dir, f"{agent_id}.md")
        agent = create_agent(
            provider_id,
            memory_file_path=memory_path,
            system_prompt=system_prompt if isinstance(system_prompt, str) else None,
        )

        load_configured_tools(agent, tool_names)

        if isinstance(system_prompt, str) and system_prompt.strip():
            has_system = any((msg or {}).get("role") == "system" for msg in getattr(agent, "messages", []) or [])
            if not has_system:
                agent.Message("system", system_prompt.strip())

        resolved_public_base_url = self._resolve_public_base_url(public_base_url, provider_id)
        user_content = self._build_user_content(provider_id, mode, message, resolved_public_base_url)
        user_content = prepend_working_path_context(user_content, working_path)
        agent.Message("user", user_content, persist=False)
        web_search_mode = self._normalize_switch(web_search, default="disabled")
        thinking_mode = self._normalize_switch(thinking, default="enabled")
        stream_runtime = AgentStreamRuntime(self._resolve_stream_callback(ctx))

        start_time = time.monotonic()
        response = stream_runtime.send(
            agent,
            {
                "run_tools": True,
                "mode": mode,
                "web_search": web_search_mode,
                "thinking": thinking_mode,
                "stream": True,
                "stream_handler": stream_runtime.on_stream_delta,
            },
        )
        min_delay_ms = 0
        try:
            config = ConfigLoader().get_config()
            node_cfg = config.get("agentNode") if isinstance(config, dict) else None
            if not isinstance(node_cfg, dict):
                node_cfg = config.get("agent_node") if isinstance(config, dict) else None
            if isinstance(node_cfg, dict):
                raw_delay = node_cfg.get("minSendDelayMs", 0)
                min_delay_ms = int(float(raw_delay))
        except Exception:
            min_delay_ms = 0
        if min_delay_ms > 0:
            elapsed = time.monotonic() - start_time
            remain = min_delay_ms / 1000 - elapsed
            if remain > 0:
                time.sleep(remain)
        output_message = self._build_output_message(response)
        final_text = self._message_text(output_message).strip()
        stream_runtime.emit_done(final_text)
        return {
            "display": self._message_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
