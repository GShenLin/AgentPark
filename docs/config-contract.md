# Config Contract

Node instance configuration lives at:

```text
memories/<graph_id>/<node_id>/config.json
```

The file must be a JSON object. Missing files, invalid JSON, and non-object JSON are distinct errors on strict paths.

Current node config schema:

```json
{
  "schemaVersion": 1
}
```

Configs without `schemaVersion` are treated as schema version 1 when read and are written back with `schemaVersion: 1` on the next service-owned write. Non-integer, less-than-1, or future schema versions are explicit format errors. Migration code belongs in `NodeConfigService`, not in individual WebUI, CLI, or runtime callers.

## Strict Paths

These operations use strict reads and must surface the original failure:

- WebUI node config Apply: `POST /api/nodes/instances/{node_id}/config`
- node config listing: `GET /api/nodes/instances/configs`
- `manage_agent_capabilities`
- `python -m src.cli config validate`
- `python -m src.cli capabilities list|enable|disable`

Strict paths must not convert read failures to `{}` or overwrite a damaged file with defaults.

## Optional Paths

Runtime recovery paths may use optional reads when missing config is an expected condition. The function name must make that behavior explicit, for example `read_node_config_optional`.

Optional reads only tolerate a missing path or missing file. Invalid JSON, non-object JSON, and unsupported `schemaVersion` values still raise explicit errors. Optional reads are not valid for user-visible Apply/list/capability mutations.

## Writes

Node config writes go through `NodeConfigService` and `src.file_transaction.atomic_write_text`.

The write path:

- normalizes the config schema version,
- serializes writes per config path,
- writes a temporary file first,
- uses `os.replace` through the shared retry helper,
- preserves the real exception message when replacement continues to fail.

## Mutation Result

Config mutation APIs return:

- `before`
- `after`
- `changed_fields`
- `effective`
- `warnings`

Capability and WebUI mutations currently use `effective: "next_agent_run"`.

## Graph Configs

Graph topology configuration lives at:

```text
memories/<graph_id>/config.json
```

Graph config files must also be JSON objects. Graph load, graph list, graph runner topology reads, event dispatch, node rename graph-reference updates, and `doctor` must surface invalid JSON or non-object JSON instead of treating the graph as empty.
