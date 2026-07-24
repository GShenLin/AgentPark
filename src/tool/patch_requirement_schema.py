from __future__ import annotations


def build_patch_requirements_schema() -> dict:
    string_schema = {"type": "string"}
    change_schema = {
        "oneOf": [
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["addition"]},
                    "text": string_schema,
                },
                "required": ["id", "kind", "text"],
                "additionalProperties": False,
            },
            {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "kind": {"type": "string", "enum": ["replacement"]},
                    "old_text": string_schema,
                    "new_text": string_schema,
                },
                "required": ["id", "kind", "old_text", "new_text"],
                "additionalProperties": False,
            },
        ]
    }
    return {
        "type": "array",
        "minItems": 1,
        "maxItems": 20,
        "items": change_schema,
    }
