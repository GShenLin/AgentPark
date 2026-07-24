from __future__ import annotations

import base64
import json
import mimetypes
import os

from src.message_protocol import MetaPart
from src.message_protocol import ResourcePart
from src.message_protocol import StructuredPart
from src.message_protocol import TextPart
from src.message_protocol import build_resource_part, build_text_envelope, envelope_text, normalize_envelope
from src.message_protocol import normalize_message_envelope
from src.video_generation_content import build_doubao_video_generation_content


def build_agent_user_content(
    provider_id: str,
    mode: str,
    message: object,
    public_base_url: object = "",
    *,
    include_images: bool = True,
):
    envelope = normalize_message_envelope(message, default_role="user")
    text_parts: list[str] = []
    image_resources: list[dict] = []
    other_resources: list[dict] = []

    for part in envelope.parts:
        if isinstance(part, TextPart):
            text = part.text.strip()
            if text:
                text_parts.append(text)
            continue
        if isinstance(part, StructuredPart):
            data = part.data
            if data is not None:
                text_parts.append(json.dumps(data, ensure_ascii=False) if isinstance(data, (dict, list)) else str(data))
            continue
        if isinstance(part, MetaPart):
            continue
        if not isinstance(part, ResourcePart):
            continue
        res = part.resource
        uri = str(res.get("uri") or "").strip()
        kind = str(res.get("kind") or "").strip().lower()
        if include_images and kind == "image" and uri:
            image_resources.append(res)
        else:
            other_resources.append(res)

    if str(mode or "").strip().lower() == "video_generation" and "doubao" in str(provider_id or "").strip().lower():
        return build_doubao_video_generation_content(
            envelope.to_dict(),
            public_base_url=public_base_url,
        )

    if str(mode or "").strip().lower() == "image_generation":
        content_parts: list[dict] = []
        merged_text = "\n".join([item for item in text_parts if item]).strip()
        if merged_text:
            content_parts.append({"type": "text", "text": merged_text})
        for resource in image_resources:
            uri = str(resource.get("uri") or "").strip()
            if uri:
                content_parts.append({"type": "reference_resource", "kind": "image", "uri": uri})
        return content_parts

    if str(mode or "").strip().lower() == "audio_generation":
        content_parts: list[dict] = []
        merged_text = "\n".join([item for item in text_parts if item]).strip()
        if merged_text:
            content_parts.append({"type": "text", "text": merged_text})
        for resource in [*image_resources, *other_resources]:
            uri = str(resource.get("uri") or "").strip()
            kind = str(resource.get("kind") or "").strip().lower()
            if uri and kind in {"audio", "image"}:
                content_parts.append({"type": "reference_resource", "kind": kind, "uri": uri})
        return content_parts

    if other_resources:
        text_parts.extend(
            [f"[{str(item.get('kind') or 'file')}] {str(item.get('uri') or '').strip()}" for item in other_resources]
        )
    merged_text = "\n".join([item for item in text_parts if item]).strip()
    provider = str(provider_id or "").strip().lower()

    if not image_resources:
        return merged_text

    if "gemini" in provider:
        local_path = _to_local_path(image_resources[0].get("uri"))
        if local_path and os.path.exists(local_path):
            return {"type": "image", "path": local_path, "text": merged_text}
        return merged_text + f"\n[image] {image_resources[0].get('uri')}"

    content_parts = []
    if merged_text:
        content_parts.append({"type": "text", "text": merged_text})
    for resource in image_resources:
        uri = str(resource.get("uri") or "").strip()
        image_url = uri
        local_path = _to_local_path(uri)
        if local_path and os.path.exists(local_path):
            try:
                with open(local_path, "rb") as f:
                    encoded = base64.b64encode(f.read()).decode("utf-8")
                mime = _image_mime(resource, local_path)
                image_url = f"data:{mime};base64,{encoded}"
            except Exception:
                image_url = uri
        content_parts.append({"type": "image_url", "image_url": {"url": image_url}})
    return content_parts


def build_agent_output_message(response: object) -> dict:
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

        audio_path = response.get("audio_path")
        if isinstance(audio_path, str) and audio_path.strip():
            parts.append(build_resource_part(uri=audio_path.strip(), kind="audio", source="agent"))
        elif isinstance(audio_path, list):
            for item in audio_path:
                uri = str(item or "").strip()
                if uri:
                    parts.append(build_resource_part(uri=uri, kind="audio", source="agent"))

        structured = {
            key: value
            for key, value in response.items()
            if key not in {
                "response",
                "text",
                "image_path",
                "video_path",
                "audio_path",
                "server_tool_calls",
                "citations",
                "response_metadata",
                "provider_requests",
            }
            and value not in (None, "")
        }
        if structured:
            parts.append({"type": "structured", "data": structured})

        if not parts:
            parts.append({"type": "text", "text": json.dumps(response, ensure_ascii=False)})
        return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")

    text = "" if response is None else str(response)
    return build_text_envelope(text, role="assistant")


def build_response_metadata_message(
    response: object,
    *,
    scope: str,
    target_message_id: object = "",
    target_tool_call_ids: object = None,
    fields: tuple[str, ...] = ("server_tool_calls", "citations", "response_metadata", "provider_requests"),
) -> dict | None:
    if not isinstance(response, dict):
        return None
    resolved_scope = str(scope or "").strip().lower()
    if resolved_scope not in {"provider_turn", "final_assistant", "agent_run"}:
        raise ValueError(f"unsupported response metadata scope: {scope}")
    structured_result = {
        key: response.get(key)
        for key in fields
        if (isinstance(response.get(key), list) or isinstance(response.get(key), dict)) and response.get(key)
    }
    if not structured_result:
        return None
    message_id = str(target_message_id or "").strip()
    call_ids = [
        str(item or "").strip()
        for item in (target_tool_call_ids if isinstance(target_tool_call_ids, list) else [])
        if str(item or "").strip()
    ]
    if message_id and call_ids:
        raise ValueError("response metadata target must be either a message or tool calls")
    if message_id:
        target = {"type": "message", "message_id": message_id}
    elif call_ids:
        target = {"type": "tool_calls", "call_ids": list(dict.fromkeys(call_ids))}
    else:
        raise ValueError("response metadata requires an explicit target")
    data = {
        "kind": "response_metadata",
        "scope": resolved_scope,
        "target": target,
        **structured_result,
    }
    response_metadata = structured_result.get("response_metadata")
    provider_response = response_metadata.get("response") if isinstance(response_metadata, dict) else None
    provider_turn_id = str(provider_response.get("id") or "").strip() if isinstance(provider_response, dict) else ""
    if provider_turn_id:
        data["provider_turn_id"] = provider_turn_id
    return normalize_envelope(
        {"role": "metadata", "parts": [{"type": "structured", "data": data}]},
        default_role="metadata",
    )


def extract_channel_meta(message: object) -> list[dict]:
    envelope = normalize_message_envelope(message, default_role="user")
    output: list[dict] = []
    for part in envelope.parts:
        if isinstance(part, MetaPart) and str(part.meta.get("channel") or "").strip():
            output.append({"type": "meta", "meta": dict(part.meta)})
    return output


def append_channel_meta(output_message: dict, meta_parts: list[dict]) -> dict:
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


def history_envelope_to_agent_message(
    envelope: dict,
    provider_id: str,
    public_base_url: object = "",
) -> dict | None:
    role = str((envelope or {}).get("role") or "").strip().lower()
    if role not in {"user", "assistant"}:
        return None
    if role == "user":
        content = build_agent_user_content(provider_id, "chat", envelope, public_base_url, include_images=False)
    else:
        content = envelope_text(envelope).strip()

    if isinstance(content, str) and not content.strip():
        return None
    if isinstance(content, list) and not content:
        return None
    if content is None:
        return None
    return {"role": role, "content": content}


def _to_local_path(uri: object) -> str:
    raw = str(uri or "").strip()
    if not raw:
        return ""
    if raw.startswith("file://"):
        return raw[7:]
    return raw


def _image_mime(resource: dict, local_path: str) -> str:
    mime = str(resource.get("mime") or "").split(";")[0].strip().lower()
    if mime.startswith("image/"):
        return mime
    guessed = mimetypes.guess_type(local_path)[0]
    if guessed and guessed.startswith("image/"):
        return guessed
    return "image/png"
