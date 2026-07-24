from __future__ import annotations

from src.workspace_execution import execute_workspace_program
from src.workspace_execution_output import serialize_workspace_result
from src.tool.patch_requirement_schema import build_patch_requirements_schema
from src.tool.task_direction_schema import UPDATE_PROPERTIES
from src.tool.task_direction_schema import UPDATE_REQUIRED
from src.workspace_checkpoint_policy import CHECKPOINT_POLICIES
from src.workspace_checkpoint_policy import validate_workspace_checkpoint_policy


def workspace_exec(stages, context_checkpoint="none", agent=None):
    policy = validate_workspace_checkpoint_policy(stages, context_checkpoint)
    result = execute_workspace_program(stages, agent=agent)
    result["context_checkpoint"] = policy
    return serialize_workspace_result(result, agent=agent)


_REFERENCE = {
    "type": "object",
    "properties": {
        "$ref": {"type": "string"},
        "path": {
            "type": "array",
            "maxItems": 16,
            "items": {"oneOf": [{"type": "string"}, {"type": "integer", "minimum": 0}]},
        },
    },
    "required": ["$ref", "path"],
    "additionalProperties": False,
}


def _value_or_reference(value_schema):
    return {"oneOf": [value_schema, _REFERENCE]}


def _operation_schema(kind, properties, required):
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "kind": {"type": "string", "enum": [kind]},
            "arguments": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
        "required": ["id", "kind", "arguments"],
        "additionalProperties": False,
    }


_STRING = {"type": "string"}
_INTEGER = {"type": "integer"}
_STRING_ARRAY = {"type": "array", "items": {"type": "string"}}
_READ_FILE_OPERATION = _operation_schema(
    "read_file",
    {
        "file_path": _value_or_reference(_STRING),
        "start_line": _value_or_reference(_INTEGER),
        "end_line": _value_or_reference(_INTEGER),
    },
    ["file_path"],
)
_SEARCH_TEXT_OPERATION = _operation_schema(
    "search_text",
    {
        "query": _value_or_reference(_STRING),
        "project_root": _value_or_reference(_STRING),
        "include_globs": _value_or_reference(_STRING_ARRAY),
        "exclude_globs": _value_or_reference(_STRING_ARRAY),
        "case_sensitive": _value_or_reference({"type": "boolean"}),
        "fixed_strings": _value_or_reference({"type": "boolean"}),
        "max_results": _value_or_reference(_INTEGER),
    },
    ["query"],
)
_LIST_FILES_OPERATION = _operation_schema(
    "list_files",
    {
        "project_root": _value_or_reference(_STRING),
        "include_globs": _value_or_reference(_STRING_ARRAY),
        "exclude_globs": _value_or_reference(_STRING_ARRAY),
        "max_results": _value_or_reference(_INTEGER),
    },
    [],
)
_RUN_COMMAND_OPERATION = _operation_schema(
    "run_command",
    {
        "command": _value_or_reference(_STRING),
        "timeout_seconds": _value_or_reference(_INTEGER),
    },
    ["command"],
)
_APPLY_PATCH_OPERATION = _operation_schema(
    "apply_patch",
    {
        "patch": _STRING,
        "encoding": _STRING,
        "return_mode": {"type": "string", "enum": ["summary", "full"]},
        "required_changes": build_patch_requirements_schema(),
    },
    ["patch", "required_changes"],
)
_UPDATE_DIRECTION_OPERATION = _operation_schema(
    "update_task_direction",
    UPDATE_PROPERTIES,
    UPDATE_REQUIRED,
)


def _stage_schema(operation_items, *, max_items):
    return {
        "type": "object",
        "properties": {
            "id": {"type": "string"},
            "operations": {
                "type": "array",
                "minItems": 1,
                "maxItems": max_items,
                "items": operation_items,
            },
        },
        "required": ["id", "operations"],
        "additionalProperties": False,
    }


_NON_MUTATING_STAGE = _stage_schema(
    {
        "oneOf": [
            _READ_FILE_OPERATION,
            _SEARCH_TEXT_OPERATION,
            _LIST_FILES_OPERATION,
            _RUN_COMMAND_OPERATION,
        ]
    },
    max_items=8,
)
_DIRECTION_MUTATION_STAGE = _stage_schema(_UPDATE_DIRECTION_OPERATION, max_items=1)
_PATCH_MUTATION_STAGE = _stage_schema(_APPLY_PATCH_OPERATION, max_items=1)


workspace_exec_declaration = {
    "type": "function",
    "function": {
        "name": "workspace_exec",
        "description": (
            "Execute a strictly structured workspace program. Stages run sequentially; operations inside one "
            "stage run concurrently. Use it to combine independent reads, searches, file inventories, and "
            "PowerShell commands without extra model round trips. It can also sequence an exclusive "
            "update_task_direction stage before an exclusive apply_patch stage. A failed stage stops the "
            "program before later stages. Ordered mutation handoffs must set context_checkpoint to "
            "retain_until_next_handoff for an intermediate patch or retire_after_verified for a "
            "terminal implementation patch. Non-handoff programs omit it or use none. "
            "Every apply_patch operation declares non-empty required_changes. The runtime verifies each "
            "declared addition or old_text-to-new_text replacement against patch +/- lines before mutation. "
            "top-level output-control fields are not supported. Each operation has an explicit id, kind, and "
            "arguments object; operation results remain individually attributable. A later stage may use an "
            "earlier operation result with {'$ref':'operation_id','path':['result','field',0]}. References to "
            "the current or a later stage are rejected. Missing read_file paths are explicit failures; "
            "discover optional files first instead of guessing their names in a batch."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "stages": {
                    "type": "array",
                    "minItems": 1,
                    "maxItems": 12,
                    "items": {
                        "oneOf": [
                            _NON_MUTATING_STAGE,
                            _DIRECTION_MUTATION_STAGE,
                            _PATCH_MUTATION_STAGE,
                        ]
                    },
                },
                "context_checkpoint": {
                    "type": "string",
                    "enum": sorted(CHECKPOINT_POLICIES),
                    "default": "none",
                },
            },
            "required": ["stages"],
            "additionalProperties": False,
        },
    },
}


workspace_exec.tool_timeout_seconds = 0
