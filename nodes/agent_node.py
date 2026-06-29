import json
import os
import time
import base64
import mimetypes
from typing import Callable

from nodes.agent_stream_runtime import AgentStreamRuntime
from nodes.agent_support.capability_setup import resolve_agent_capabilities
from nodes.agent_mcp_loader import (
    inject_mcp_server_context,
    register_mcp_server_tools,
    with_mcp_caller_context,
)
from nodes.agent_plugin_loader import resolve_plugin_capabilities
from nodes.agent_plugin_tool_loader import register_plugin_tool_definitions
from nodes.agent_skill_loader import (
    load_node_skills,
)
from nodes.agent_skill_scripts import register_skill_script_tools
from nodes.agent_tool_loader import load_configured_tools
from nodes.agent_node_settings import resolve_agent_node_settings
from nodes.base_node import BaseNode
from nodes.agent_working_path_context import build_working_path_prompt
from src.capabilities.registry import CapabilityRegistry
from src.config_loader import ConfigLoader
from src.media_resource_utils import resolve_public_base_url
from src.message_protocol import build_resource_part, build_text_envelope, envelope_text, normalize_envelope
from src.operational_memory import build_operational_memory_summary
from src.providers import create_agent
from src.runtime_cancellation import raise_if_cancel_requested
from src.switch_utils import parse_switch_mode
from src.web_backend.node_config_service import read_node_config_optional
from src.web_backend.node_memory_store import load_recent_node_memory_records
from src.web_backend.node_goal_runtime import node_goal_context
from src.video_generation_content import build_doubao_video_generation_content


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
        "plugins": [],
        "tools": [],
        "mcp_servers": [],
        "web_search": "disabled",
        "thinking": "disabled",
        "reasoning_effort": "high",
    }
    config_schema = {
        "provider_id": {"type": "text", "label": "provider_id"},
        "system_prompt": {"type": "text", "label": "system_prompt"},
        "mode": {"type": "text", "label": "mode"},
        "plugins": {
            "type": "multiselect",
            "label": "plugins",
            "options": [],
        },
        "tools": {
            "type": "multiselect",
            "label": "tools",
            "options": [],
        },
        "mcp_servers": {
            "type": "multiselect",
            "label": "mcp_servers",
            "options": [],
        },
        "web_search": {"type": "text", "label": "web_search"},
        "thinking": {"type": "text", "label": "thinking"},
        "reasoning_effort": {
            "type": "select",
            "label": "reasoning_effort",
            "options": [
                {"value": "minimal", "label": "minimal"},
                {"value": "low", "label": "low"},
                {"value": "medium", "label": "medium"},
                {"value": "high", "label": "high"},
                {"value": "xhigh", "label": "xhigh"},
            ],
        },
    }

    def get_config_schema(self, context: dict | None = None) -> dict:
        schema = super().get_config_schema(context)
        ctx = context if isinstance(context, dict) else {}
        provider_id = str(ctx.get("provider_id") or "").strip()
        provider_features = {}
        if provider_id:
            try:
                provider_features = dict(ConfigLoader().get_all_providers().get(provider_id, {}).get("features") or {})
            except Exception:
                provider_features = {}
        capability_payload = CapabilityRegistry().discover_payload(context)
        for kind, field in (
            ("tool", "tools"),
            ("mcp", "mcp_servers"),
            ("skill", "skills"),
            ("plugin", "plugins"),
        ):
            field_schema = dict(schema.get(field) or {})
            field_schema["type"] = "multiselect"
            field_schema["options"] = list((capability_payload.get(kind) or {}).get("available") or [])
            schema[field] = field_schema
        for field in ("web_search", "thinking", "reasoning_effort"):
            if field not in schema:
                continue
            field_schema = dict(schema.get(field) or {})
            feature = provider_features.get(field) if isinstance(provider_features, dict) else None
            if isinstance(feature, dict):
                field_schema["provider_feature"] = dict(feature)
                field_schema["description"] = self._provider_feature_description(field, feature)
            schema[field] = field_schema
        terminal_keys = ("tools", "mcp_servers", "skills", "plugins")
        ordered_schema = {
            key: value
            for key, value in schema.items()
            if key not in terminal_keys
        }
        for key in terminal_keys:
            if key in schema:
                ordered_schema[key] = schema[key]
        schema = ordered_schema
        return schema

    @staticmethod
    def _provider_feature_description(field: str, feature: dict) -> str:
        supported = bool(feature.get("supported"))
        values = feature.get("values")
        allowed = ", ".join(str(item) for item in values if str(item or "").strip()) if isinstance(values, list) else ""
        requires = str(feature.get("requires") or "").strip()
        if supported:
            suffix = f" Supported values: {allowed}." if allowed else ""
            return f"{field} is supported by the selected provider.{suffix}"
        if requires:
            return f"{field} is not available for this provider until {requires}."
        return f"{field} is not supported by the selected provider."

    @staticmethod
    def _to_local_path(uri: object) -> str:
        raw = str(uri or "").strip()
        if not raw:
            return ""
        if raw.startswith("file://"):
            return raw[7:]
        return raw

    def _build_user_content(
        self,
        provider_id: str,
        mode: str,
        message: object,
        public_base_url: object = "",
        *,
        include_images: bool = True,
    ):
        envelope = normalize_envelope(message, default_role="user")
        parts = envelope.get("parts") if isinstance(envelope, dict) else []
        text_parts: list[str] = []
        image_resources: list[dict] = []
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
            if part_type == "structured":
                data = part.get("data")
                if data is not None:
                    text_parts.append(json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data))
                continue
            if part_type == "meta":
                meta = part.get("meta")
                if meta:
                    text_parts.append(json.dumps({"meta": meta}, ensure_ascii=False))
                continue
            if part_type != "resource":
                continue
            res = part.get("resource")
            if not isinstance(res, dict):
                continue
            uri = str(res.get("uri") or "").strip()
            kind = str(res.get("kind") or "").strip().lower()
            if include_images and kind == "image" and uri:
                image_resources.append(res)
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

        if not image_resources:
            return merged_text

        # Gemini supports image via {"type":"image","path":...,"text":...}
        if "gemini" in provider:
            local_path = self._to_local_path(image_resources[0].get("uri"))
            if local_path and os.path.exists(local_path):
                return {"type": "image", "path": local_path, "text": merged_text}
            return merged_text + f"\n[image] {image_resources[0].get('uri')}"

        # Doubao/OpenAI-compatible payload with image_url parts.
        content_parts = []
        if merged_text:
            content_parts.append({"type": "text", "text": merged_text})
        for resource in image_resources:
            uri = str(resource.get("uri") or "").strip()
            image_url = uri
            local_path = self._to_local_path(uri)
            if local_path and os.path.exists(local_path):
                try:
                    with open(local_path, "rb") as f:
                        encoded = base64.b64encode(f.read()).decode("utf-8")
                    mime = self._image_mime(resource, local_path)
                    image_url = f"data:{mime};base64,{encoded}"
                except Exception:
                    image_url = uri
            content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
        return content_parts

    @staticmethod
    def _image_mime(resource: dict, local_path: str) -> str:
        mime = str(resource.get("mime") or "").split(";")[0].strip().lower()
        if mime.startswith("image/"):
            return mime
        guessed = mimetypes.guess_type(local_path)[0]
        if guessed and guessed.startswith("image/"):
            return guessed
        return "image/png"

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
    def _extract_channel_meta(message: object) -> list[dict]:
        envelope = normalize_envelope(message, default_role="user")
        output: list[dict] = []
        for part in envelope.get("parts") or []:
            if not isinstance(part, dict):
                continue
            if str(part.get("type") or "").strip().lower() != "meta":
                continue
            meta = part.get("meta")
            if isinstance(meta, dict) and str(meta.get("channel") or "").strip():
                output.append({"type": "meta", "meta": dict(meta)})
        return output

    @staticmethod
    def _append_channel_meta(output_message: dict, meta_parts: list[dict]) -> dict:
        if not meta_parts:
            return output_message
        envelope = normalize_envelope(output_message, default_role="assistant")
        parts = envelope.get("parts")
        if not isinstance(parts, list):
            parts = []
        existing_keys = set()
        for part in parts:
            if not isinstance(part, dict) or str(part.get("type") or "").strip().lower() != "meta":
                continue
            meta = part.get("meta")
            if isinstance(meta, dict):
                existing_keys.add(
                    (
                        str(meta.get("channel") or ""),
                        str(meta.get("accountId") or ""),
                        str(meta.get("from") or ""),
                    )
                )
        for part in meta_parts:
            meta = part.get("meta") if isinstance(part, dict) else None
            key = (
                str((meta or {}).get("channel") or ""),
                str((meta or {}).get("accountId") or ""),
                str((meta or {}).get("from") or ""),
            )
            if key not in existing_keys:
                parts.append(part)
                existing_keys.add(key)
        envelope["parts"] = parts
        return envelope

    def _load_node_history_messages(
        self,
        context: dict,
        current_message: object,
        provider_id: str,
        public_base_url: object = "",
    ) -> list[dict]:
        messages_path = self._resolve_messages_path(context)
        memory_path = self._resolve_memory_path(context)
        if not messages_path:
            return []

        current = normalize_envelope(current_message, default_role="user")
        current_id = str(current.get("id") or "").strip()
        history_message_limit = resolve_agent_node_settings(ConfigLoader().get_config()).history_message_limit
        records = load_recent_node_memory_records(
            memory_path,
            messages_path,
            limit=history_message_limit + 1,
        )

        history: list[dict] = []
        for item in records:
            envelope = normalize_envelope(item, default_role="assistant")
            if current_id and str(envelope.get("id") or "").strip() == current_id:
                continue
            message = self._history_envelope_to_agent_message(envelope, provider_id, public_base_url)
            if message is not None:
                history.append(message)
        return history[-history_message_limit:]

    def _history_envelope_to_agent_message(self, envelope: dict, provider_id: str, public_base_url: object = "") -> dict | None:
        role = str((envelope or {}).get("role") or "").strip().lower()
        if role not in {"user", "assistant"}:
            return None
        if role == "user":
            content = self._build_user_content(provider_id, "chat", envelope, public_base_url, include_images=False)
        else:
            content = envelope_text(envelope).strip()

        if isinstance(content, str) and not content.strip():
            return None
        if isinstance(content, list) and not content:
            return None
        if content is None:
            return None
        return {"role": role, "content": content}

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
        memory_path_for_config = self._resolve_memory_path(ctx)
        agent_dir = os.path.dirname(memory_path_for_config) if memory_path_for_config else ""
        config_path = os.path.join(agent_dir, "config.json")

        config_data = None
        if os.path.exists(config_path):
            try:
                data = read_node_config_optional(config_path)
            except Exception as exc:
                raise ValueError(f"failed to read agent config: {exc}") from exc
            if not isinstance(data, dict):
                raise ValueError("agent config must be a JSON object")
            config_data = data

        def setting(name: str, default=None):
            if config_data is not None and name in config_data:
                return config_data.get(name, default)
            return ctx.get(name, default)

        provider_id = str(setting("provider_id", "") or "").strip()
        system_prompt = setting("system_prompt")
        mode = str(setting("mode", "chat") or "chat").strip() or "chat"
        web_search = setting("web_search")
        thinking = setting("thinking")
        reasoning_effort = setting("reasoning_effort")
        public_base_url = setting("public_base_url")
        working_path = str(setting("working_path", "") or "").strip()
        capability_plan = resolve_agent_capabilities(
            setting,
            node_id=agent_id,
            load_skills=load_node_skills,
            resolve_plugins=resolve_plugin_capabilities,
        )
        mcp_settings = with_mcp_caller_context(
            capability_plan.mcp_settings,
            graph_id=graph_id,
            node_id=agent_id,
        )

        if not provider_id:
            raise ValueError("provider_id is required")
        input_message = normalize_envelope(message, default_role="user")
        channel_meta_parts = self._extract_channel_meta(input_message)

        memory_path = self._resolve_memory_path(ctx)
        agent = create_agent(
            provider_id,
            memory_file_path=memory_path,
            system_prompt=system_prompt if isinstance(system_prompt, str) else None,
            internal_memory_enabled=False,
        )
        agent._aitools_graph_id = graph_id
        agent._aitools_node_id = agent_id
        agent._aitools_node_type_id = "agent_node"
        agent.operational_memory_gate_enabled = True
        agent.tool_context_compaction_gate_enabled = True
        cancel_source = ctx.get("cancel_event") or ctx.get("cancel_check")
        if cancel_source is not None:
            agent.cancel_event = cancel_source
            agent.cancel_check = ctx.get("cancel_check") or cancel_source
        if capability_plan.skill_resource_roots:
            agent._aitools_skill_resource_roots = capability_plan.skill_resource_roots

        load_configured_tools(agent, capability_plan.tool_names)
        if capability_plan.plugin_capabilities.tool_definitions:
            register_plugin_tool_definitions(agent, capability_plan.plugin_capabilities.tool_definitions)
        skill_definitions = [
            *capability_plan.selected_skill_definitions,
            *capability_plan.plugin_capabilities.skill_definitions,
        ]
        register_skill_script_tools(agent, skill_definitions)
        if capability_plan.mcp_server_names:
            register_mcp_server_tools(agent, list(capability_plan.mcp_server_names), settings=mcp_settings)

        if isinstance(system_prompt, str) and system_prompt.strip():
            has_system = any((msg or {}).get("role") == "system" for msg in getattr(agent, "messages", []) or [])
            if not has_system:
                agent.Message("system", system_prompt.strip())
        working_path_prompt = build_working_path_prompt(working_path)
        if working_path_prompt:
            agent.Message("system", working_path_prompt, persist=False)
        operational_memory_summary = build_operational_memory_summary(
            os.path.join(os.path.dirname(memory_path), "operational_memory.json") if memory_path else ""
        )
        if operational_memory_summary:
            agent.Message("system", operational_memory_summary, persist=False)
        goal_context = node_goal_context(config_data or ctx)
        if goal_context:
            agent.Message("system", goal_context, persist=False)
        if capability_plan.mcp_server_names:
            inject_mcp_server_context(agent, list(capability_plan.mcp_server_names), settings=mcp_settings)
        self._inject_configured_skills(
            agent,
            {"skills": list(capability_plan.skill_names)},
            node_id=agent_id,
            extra_skills=skill_definitions,
        )

        resolved_public_base_url = resolve_public_base_url(public_base_url, provider_id)
        for history_message in self._load_node_history_messages(ctx, input_message, provider_id, resolved_public_base_url):
            agent.Message(history_message["role"], history_message["content"], persist=False)

        user_content = self._build_user_content(provider_id, mode, input_message, resolved_public_base_url)
        agent.Message("user", user_content, persist=False)
        web_search_mode = parse_switch_mode(web_search, default="disabled", allow_auto=False)
        thinking_mode = parse_switch_mode(thinking, default="disabled", allow_auto=False)
        if reasoning_effort is None:
            reasoning_effort = self.config_defaults["reasoning_effort"]
        stream_runtime = AgentStreamRuntime(self._resolve_stream_callback(ctx))

        start_time = time.monotonic()
        raise_if_cancel_requested(cancel_source)
        response = stream_runtime.send(
            agent,
            {
                "run_tools": True,
                "mode": mode,
                "web_search": web_search_mode,
                "thinking": thinking_mode,
                "reasoning_effort": reasoning_effort,
                "stream": True,
                "stream_handler": stream_runtime.on_stream_delta,
            },
        )
        min_delay_ms = resolve_agent_node_settings(ConfigLoader().get_config()).min_send_delay_ms
        if min_delay_ms > 0:
            elapsed = time.monotonic() - start_time
            remain = min_delay_ms / 1000 - elapsed
            if remain > 0:
                deadline = time.monotonic() + remain
                while True:
                    raise_if_cancel_requested(cancel_source)
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    time.sleep(min(0.05, remaining))
        raise_if_cancel_requested(cancel_source)
        output_message = self._build_output_message(response)
        output_message = self._append_channel_meta(output_message, channel_meta_parts)
        final_text = envelope_text(output_message).strip()
        stream_runtime.emit_done(final_text)
        return {
            "display": envelope_text(output_message),
            "routes": [{"output_index": 0, "payload": output_message}],
        }
