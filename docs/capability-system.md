# Capability System

AgentPark exposes four node-scoped capability kinds:

- `tool`
- `mcp`
- `skill`
- `plugin`

Each kind keeps its own loader. The shared query surface is `CapabilityRegistry` in `src/capabilities/registry.py`.

## Descriptor

Registry discovery returns `CapabilityDescriptor` objects:

```text
kind: tool | mcp | skill | plugin
id: string
label: string
description: string
source: workspace | plugin | skill | system
enabled: bool
dependencies: list[CapabilityRef]
config_schema: object
status: available | selected | unavailable | error
diagnostics: list[string]
```

WebUI, AI tools, and CLI should consume this descriptor shape instead of stitching together loader-specific option lists.

Each capability-kind group in `discover_payload()` includes `schema_version`. Consumers should branch on that value before depending on new descriptor fields.

## Selection

Node config fields remain:

- `tools`
- `mcp_servers`
- `skills`
- `plugins`

These fields must be arrays of strings. Invalid field types are configuration errors.

## Dependencies

Selected skills expose declared MCP dependencies as `dependencies`.

Selected plugins expose contributed tools, skills, MCP servers, and `configSchema`. Plugin-originated contributions must stay traceable through the plugin descriptor.

## Skill Script Tools

Selected skills can expose executable script tools only through explicit `skill.json` declarations. The runtime does not register arbitrary files under `scripts/`.

Script declarations are loaded with the skill and registered as generated external tools named `skill__<skill>__<script>`. Read-only scripts are enabled by default; write-capable scripts require `allowWrite: true` and `enabled: true` in the declaration.

Script execution is process-bound by declared `cwd` and `timeoutSeconds`. Tool results preserve stdout, stderr, exit code, timeout state, and typed argument validation errors.

## MCP Lifecycle Diagnostics

MCP tool materialization records lifecycle state:

- `starting`
- `ready`
- `failed`
- `stopped`

Capability discovery includes the latest MCP lifecycle diagnostics for each MCP descriptor. A failed MCP startup is surfaced as descriptor `status: error` with the original failure message.

The current runtime uses session-scoped MCP materialization and tool calls. Long-lived process supervision is a separate boundary from descriptor diagnostics.

## Effective Time

Capability selection changes currently take effect on the next Agent run. UI and CLI should show this as `next_agent_run`; they should not claim hot reload behavior.

## Discovery Cache

Tool, skill, and plugin option discovery uses a short-lived in-process cache to avoid repeated filesystem scans during frequent UI schema requests. The cache is invalidated by root directory marker changes, TTL expiry, or an explicit refresh.

MCP remote tool listing uses a successful-result TTL cache. The default TTL is 30 seconds and can be overridden per server with `toolListTtlSeconds`.

Manual refresh surfaces:

```bat
python -m src.cli capabilities list --graph <graph_id> --node <node_id> --refresh
```

AI capability discovery can also pass `refresh: true` to `manage_agent_capabilities`.

Skill instruction loading is not cached. `SKILL.md`, resources, dependencies, and script manifests are read fresh when a node run loads the selected skills.
