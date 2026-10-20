"""Contracts for model-authored forms and user-authored responses."""
from __future__ import annotations

from typing import Any

FIELD_TYPES = {"text", "textarea", "select", "multiselect", "checkbox", "file"}


class InteractionValidationError(ValueError):
    pass


def _text(value: Any, name: str, limit: int, *, required: bool = False) -> str:
    if not isinstance(value, str) or len(value) > limit or (required and not value.strip()):
        raise InteractionValidationError(f"{name} must be {'a non-empty' if required else 'a'} string (max {limit})")
    return value.strip()


def normalize_interaction_schema(*, title: Any, description: Any = "", fields: Any = None,
                                 confirm_label: Any = "确认") -> dict:
    if fields is None or fields == []:
        fields = [{"id": "message", "type": "textarea", "label": "补充信息", "required": True}]
    if not isinstance(fields, list) or len(fields) > 20:
        raise InteractionValidationError("fields must be an array of at most 20 fields")
    normalized = []
    ids: set[str] = set()
    for raw in fields:
        if not isinstance(raw, dict):
            raise InteractionValidationError("each field must be an object")
        field_id = _text(raw.get("id"), "field.id", 64, required=True)
        if field_id in ids or not all(c.isalnum() or c in "-_" for c in field_id):
            raise InteractionValidationError("field.id must be unique and contain only letters, numbers, - or _")
        ids.add(field_id)
        kind = raw.get("type")
        if not isinstance(kind, str) or kind not in FIELD_TYPES:
            raise InteractionValidationError(f"field.type must be one of {sorted(FIELD_TYPES)}")
        field = {"id": field_id, "type": kind,
                 "label": _text(raw.get("label"), "field.label", 500, required=True)}
        for key, limit in (("description", 1000), ("placeholder", 500)):
            field[key] = _text(raw.get(key, ""), key, limit)
        for key in ("required", "multiple"):
            value = raw.get(key, False)
            if not isinstance(value, bool):
                raise InteractionValidationError(f"{key} must be boolean")
            if key == "required" or kind == "file":
                field[key] = value
        if kind in {"select", "multiselect"}:
            options = raw.get("options")
            if not isinstance(options, list) or not 1 <= len(options) <= 100:
                raise InteractionValidationError("options is required and must contain 1 to 100 items")
            field["options"] = []
            seen: set[str] = set()
            for option in options:
                if not isinstance(option, dict):
                    raise InteractionValidationError("option must be an object")
                value = _text(option.get("value"), "option.value", 500, required=True)
                disabled = option.get("disabled", False)
                if value in seen or not isinstance(disabled, bool):
                    raise InteractionValidationError("options must have unique values and boolean disabled flags")
                seen.add(value)
                field["options"].append({"value": value, "label": _text(option.get("label", value), "option.label", 500), "disabled": disabled})
        if kind == "file":
            field["accept"] = _text(raw.get("accept", ""), "accept", 500)
        if "default" in raw:
            if kind == "file":
                raise InteractionValidationError("file fields cannot have default values")
            validate_value(field, raw["default"], enforce_required=False)
            field["default"] = raw["default"]
        normalized.append(field)
    return {"title": _text(title, "title", 500, required=True),
            "description": _text(description, "description", 4000),
            "confirm_label": _text(confirm_label, "confirm_label", 80, required=True), "fields": normalized}


def validate_value(field: dict, value: Any, *, enforce_required: bool = True) -> None:
    kind, label = field["type"], field["label"]
    required = enforce_required and field["required"]
    if kind in {"text", "textarea", "select"}:
        if not isinstance(value, str) or (required and not value.strip()):
            raise InteractionValidationError(f"{label}: 请填写文本或选择选项")
    elif kind == "checkbox":
        if not isinstance(value, bool) or (required and not value):
            raise InteractionValidationError(f"{label}: 请勾选确认")
    elif kind in {"multiselect", "file"}:
        if not isinstance(value, list) or (required and not value):
            raise InteractionValidationError(f"{label}: 至少选择一项")
    if kind in {"select", "multiselect"}:
        choices = [value] if kind == "select" and value else value if kind == "multiselect" else []
        allowed = {o["value"] for o in field["options"] if not o["disabled"]}
        if any(not isinstance(v, str) or v not in allowed for v in choices) or len(set(choices)) != len(choices):
            raise InteractionValidationError(f"{label}: 包含无效、禁用或重复选项")
    if kind == "file":
        if not field["multiple"] and len(value) > 1:
            raise InteractionValidationError(f"{label}: 只允许一个文件")
        for item in value:
            if not isinstance(item, dict) or any(not isinstance(item.get(k), str) or not item[k] for k in ("path", "name")):
                raise InteractionValidationError(f"{label}: 文件上传结果无效")


def validate_interaction_response(schema: dict, response: Any) -> dict:
    if not isinstance(response, dict):
        raise InteractionValidationError("response must be an object")
    values, files = response.get("values", {}), response.get("files", {})
    if not isinstance(values, dict) or not isinstance(files, dict):
        raise InteractionValidationError("values and files must be objects")
    fields = schema["fields"]
    if set(values) - {f["id"] for f in fields if f["type"] != "file"} or set(files) - {f["id"] for f in fields if f["type"] == "file"}:
        raise InteractionValidationError("response contains unknown fields")
    for field in fields:
        default = [] if field["type"] in {"file", "multiselect"} else False if field["type"] == "checkbox" else ""
        source = files if field["type"] == "file" else values
        validate_value(field, source.get(field["id"], default))
    return {"values": values, "files": files}
