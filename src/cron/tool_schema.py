"""Provider-facing schemas are derived from the validated input contracts."""
from copy import deepcopy

from .schedule import CreateJob, DeleteJob, UpdateJob


def _inline_schema(model):
    schema = model.model_json_schema()
    definitions = schema.pop("$defs", {})

    def expand(value):
        if isinstance(value, list):
            return [expand(item) for item in value]
        if not isinstance(value, dict):
            return value
        if "$ref" in value:
            return expand(deepcopy(definitions[value["$ref"].rsplit("/", 1)[1]]))
        return {key: expand(item) for key, item in value.items() if key not in {"title", "discriminator"}}

    return expand(schema)


def declaration(name, description, schema):
    return {"type": "function", "function": {"name": name, "description": description, "parameters": schema}}


cron_create_declaration = declaration("cron_create",
    "Schedule a future wakeup of THIS AgentPark node. Same name and specification is idempotent. "
    "Supports at (ISO8601 with offset), every (seconds >=60), cron (five fields plus IANA timezone). "
    "Requires a running backend to deliver; persisted across restarts. No new node or graph link required.",
    _inline_schema(CreateJob))
cron_list_declaration = declaration("cron_list",
    "List this node's schedules and last 30 runs, including pending/running/failed status and errors. "
    "Timestamps are Unix seconds UTC. Use revision when editing or deleting.",
    {"type": "object", "properties": {}, "required": [], "additionalProperties": False})
_update = _inline_schema(UpdateJob)
_changes = {key: value for key, value in _update["properties"].items() if key not in {"job_id", "expected_revision"}}
for _field in _changes.values():
    _field.pop("default", None)
    if "anyOf" in _field:
        _variants = [variant for variant in _field.pop("anyOf") if variant.get("type") != "null"]
        if len(_variants) == 1:
            _field.update(_variants[0])
        else:
            _field["anyOf"] = _variants
cron_update_declaration = declaration("cron_update",
    "Edit this node's schedule using its latest revision. changes.enabled=false pauses; true resumes. "
    "Changing time or pausing cancels pending runs; already running actions continue. Omit unchanged fields; null is invalid.",
    {"type": "object", "properties": {
        "job_id": _update["properties"]["job_id"],
        "expected_revision": _update["properties"]["expected_revision"],
        "changes": {"type": "object", "properties": _changes, "minProperties": 1, "additionalProperties": False},
    }, "required": ["job_id", "expected_revision", "changes"], "additionalProperties": False})
cron_delete_declaration = declaration("cron_delete",
    "Delete this node's schedule and cancel its pending runs. Already running actions continue. Run history is retained.",
    _inline_schema(DeleteJob))
