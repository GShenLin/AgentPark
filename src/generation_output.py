import json
from dataclasses import dataclass
from typing import Literal, Mapping

from src.message_protocol import build_resource_part, normalize_envelope


JsonFallbackMode = Literal["never", "when_no_parts", "when_only_structured"]


@dataclass(frozen=True)
class ResourceOutputField:
    name: str
    kind: str
    source: str
    allow_list: bool = False


@dataclass(frozen=True)
class StructuredOutputSpec:
    base: Mapping[str, object] | None = None
    field_names: tuple[str, ...] = ()
    include_empty: bool = False
    count_field: str | None = None
    count_name: str | None = None
    count_scalar: bool = True


def build_generation_output_message(
    response: object,
    *,
    text_fields: tuple[str, ...],
    resource_fields: tuple[ResourceOutputField, ...] = (),
    structured: StructuredOutputSpec | None = None,
    json_fallback: JsonFallbackMode = "never",
) -> dict:
    if not isinstance(response, dict):
        return normalize_envelope({"role": "assistant", "parts": [{"type": "text", "text": str(response or "")}]})

    parts: list[dict] = []
    response_text = _first_text_field(response, text_fields)
    if response_text:
        parts.append({"type": "text", "text": response_text})

    for field in resource_fields:
        _append_resource_parts(parts, response.get(field.name), field)

    if structured is not None:
        data = _structured_data(response, structured)
        if data or structured.include_empty:
            parts.append({"type": "structured", "data": data})

    if _should_add_json_fallback(parts, json_fallback):
        parts.insert(0, {"type": "text", "text": json.dumps(response, ensure_ascii=False)})

    return normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")


def _first_text_field(response: dict, fields: tuple[str, ...]) -> str:
    for field in fields:
        text = str(response.get(field) or "").strip()
        if text:
            return text
    return ""


def _append_resource_parts(parts: list[dict], value: object, field: ResourceOutputField) -> None:
    if isinstance(value, str):
        uri = value.strip()
        if uri:
            parts.append(build_resource_part(uri=uri, kind=field.kind, source=field.source))
        return

    if not field.allow_list or not isinstance(value, list):
        return

    for item in value:
        uri = str(item or "").strip()
        if uri:
            parts.append(build_resource_part(uri=uri, kind=field.kind, source=field.source))


def _structured_data(response: dict, spec: StructuredOutputSpec) -> dict:
    data = dict(spec.base or {})
    for key in spec.field_names:
        value = response.get(key)
        if value is not None and value != "":
            data[key] = value

    if spec.count_field and spec.count_name:
        value = response.get(spec.count_field)
        if isinstance(value, list):
            data[spec.count_name] = len(value)
        elif spec.count_scalar and isinstance(value, str):
            data[spec.count_name] = 1
    return data


def _should_add_json_fallback(parts: list[dict], mode: JsonFallbackMode) -> bool:
    if mode == "never":
        return False
    if mode == "when_no_parts":
        return not parts
    if mode == "when_only_structured":
        return len(parts) == 1 and parts[0].get("type") == "structured"
    raise ValueError(f"Unsupported JSON fallback mode: {mode}")
