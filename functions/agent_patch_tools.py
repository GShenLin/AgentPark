from __future__ import annotations

from functions.apply_patch_tool import apply_patch as apply_patch_unchecked
from src.tool.patch_requirement_schema import build_patch_requirements_schema
from src.workspace_patch_requirements import validate_workspace_patch_requirements


def apply_patch(
    patch,
    required_changes,
    encoding="utf-8",
    return_mode="summary",
    agent=None,
):
    validate_workspace_patch_requirements(patch, required_changes)
    return apply_patch_unchecked(
        patch=patch,
        encoding=encoding,
        return_mode=return_mode,
        agent=agent,
    )


apply_patch_declaration = {
    "type": "function",
    "function": {
        "name": "apply_patch",
        "description": (
            "Apply a Codex-style patch after verifying every declared critical addition or replacement "
            "against its +/- lines. required_changes is mandatory for both direct and workspace mutations."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": "Patch text using *** Begin Patch / *** End Patch sections.",
                },
                "required_changes": build_patch_requirements_schema(),
                "encoding": {
                    "type": "string",
                    "description": "Text encoding for reading and writing files (default: utf-8).",
                    "default": "utf-8",
                },
                "return_mode": {
                    "type": "string",
                    "enum": ["summary", "full"],
                    "description": "Model-visible return detail.",
                    "default": "summary",
                },
            },
            "required": ["patch", "required_changes"],
            "additionalProperties": False,
        },
    },
}


__all__ = ["apply_patch", "apply_patch_declaration"]
