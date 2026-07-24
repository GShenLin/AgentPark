"""Normalized Agent image-generation input contract."""
from __future__ import annotations

from src.media_resource_utils import parse_resource_list


def latest_image_generation_input(messages: object, configured_references: object = None) -> tuple[str, list[str]]:
    references = parse_resource_list(configured_references)
    if not isinstance(messages, list):
        return "", references
    for message in reversed(messages):
        if not isinstance(message, dict) or message.get("role") != "user":
            continue
        content = message.get("content")
        if isinstance(content, str):
            return content.strip(), references
        if isinstance(content, dict):
            text = str(content.get("text") or "").strip()
            path = str(content.get("path") or "").strip()
            if str(content.get("type") or "").strip().lower() == "image" and path:
                references.append(path)
            return text, _dedupe(references)
        if not isinstance(content, list):
            continue
        text_parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip().lower()
            if item_type == "text":
                text = str(item.get("text") or "").strip()
                if text:
                    text_parts.append(text)
            elif item_type == "reference_resource" and str(item.get("kind") or "").strip().lower() == "image":
                uri = str(item.get("uri") or "").strip()
                if uri:
                    references.append(uri)
            elif item_type == "image_url":
                image_url = item.get("image_url")
                uri = str(image_url.get("url") or "").strip() if isinstance(image_url, dict) else str(image_url or "").strip()
                if uri:
                    references.append(uri)
        return "\n".join(text_parts).strip(), _dedupe(references)
    return "", _dedupe(references)


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(str(value or "").strip() for value in values if str(value or "").strip()))
