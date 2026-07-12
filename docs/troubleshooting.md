# Troubleshooting

## Run Doctor

Use the offline CLI when the WebUI is unavailable:

```bat
python -m src.cli doctor
python -m src.cli doctor --json
```

Doctor checks Python, Node, npm, `rg`, workspace config, provider config, MCP server manifests, skill manifests, plugin manifests, graph config JSON files, and node config JSON files. JSON output uses `checks[].name`, `checks[].status`, `checks[].detail`, and optional `checks[].path`.

Common check prefixes:

- `providers`: `config/moduleProvider.json` and provider feature normalization
- `mcp_server:<name>`: MCP transport and required fields
- `skill:<id>`: `SKILL.md`, `skill.json`, resources, and `agents/*.yaml`
- `plugin:<id>`: `agentpark.plugin.json` or adapted plugin manifest
- `graph_config:<graph>`: persisted graph topology config
- `node_config:<graph>/<node>`: persisted node config contract

## Damaged Node Config

Symptoms:

- WebUI config list returns an explicit JSON error.
- Apply fails with `node config contains invalid JSON`.
- `manage_agent_capabilities` returns `NodeConfigFormatError`.

Commands:

```bat
python -m src.cli config validate --graph <graph_id> --node <node_id>
python -m src.cli doctor --json
```

Fix the reported `memories/<graph_id>/<node_id>/config.json` file as a JSON object. Do not replace it with `{}` unless the node is intentionally being rebuilt from scratch.

## Damaged Graph Config

Symptoms:

- Graph list or graph load returns an explicit JSON error.
- Graph runner events include `graph_config_read_failed`.
- `doctor` reports `graph_config:<graph_id>`.

Fix the reported `memories/<graph_id>/config.json` file as a JSON object. A damaged graph config is not treated as an empty topology because that can hide broken links and node references.

## Capability Selection

List available and selected capabilities without starting FastAPI:

```bat
python -m src.cli capabilities list --graph <graph_id> --node <node_id>
```

Enable or disable a capability:

```bat
python -m src.cli capabilities enable --kind skill --name openai-docs --graph <graph_id> --node <node_id>
python -m src.cli capabilities disable --kind mcp --name docs --graph <graph_id> --node <node_id>
```

Changes take effect on the next Agent run.

If a newly added tool, skill, or plugin does not appear immediately, refresh discovery caches:

```bat
python -m src.cli capabilities list --graph <graph_id> --node <node_id> --refresh --json
```

## Runtime Recovery

Startup and runner recovery follow the state contract in `docs/runtime-state-machine.md`.

Useful signals:

- `startup_node_state_recovered` in `memories/<graph_id>/runner.events.jsonl`
- `node_working_recovered` in `memories/<graph_id>/runner.events.jsonl`
- `pending_count`, `inflight`, `_stop_requested`, and `state` in the node config

If a node is stuck in `working` without `inflight`, start or wake the graph runner. It should return the node to `idle` and keep pending work queued. If a node is `working` with `inflight`, do not manually requeue it unless the process is known dead; use node stop/cancel first so the active operation has a chance to finish or observe cancellation.

## Web API Access Boundaries

The file API only resolves paths under the AgentPark workspace root. Relative paths are resolved from the workspace root, and absolute paths or `file://` URLs outside that root return `403`. The workspace root itself cannot be renamed or deleted through `/api/files/*`.

The Web API accepts requests from all browser origins. Chrome Private Network Access preflight requests are also accepted without additional environment configuration so remote WebUIs and devices on the local network can connect directly.

## MCP Startup Failures

MCP materialization records lifecycle diagnostics. To inspect them through the shared descriptor model:

```bat
python -m src.cli capabilities list --graph <graph_id> --node <node_id> --json
```

Look under `capabilities.mcp.descriptors[].diagnostics`.

Current states include `starting`, `ready`, `failed`, and `stopped`. A failed startup appears as `status: error` with the original exception text. The current runtime uses session-scoped MCP materialization; long-lived process supervision is not yet a separate daemon.

## Packaged Build Recovery

Packaged artifacts include the offline CLI in the same executable:

```bat
dist\AgentPark.exe doctor --json
dist\AgentPark.exe capabilities list --graph <graph_id> --node <node_id> --json
```

The package includes `docs/`, `skills/`, and `plugins/` beside the executable. This keeps doctor checks and default capability discovery aligned with the runtime resources used by source checkout runs.
