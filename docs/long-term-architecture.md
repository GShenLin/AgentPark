# Long-Term Architecture

This document records the P3 boundary decisions from `TODO.md`. These are not compatibility shims; they define where future optimization work should attach without weakening the current Python contracts.

## Rust Sidecar Evaluation

Do not start with a full rewrite. A Rust sidecar is only justified where AITools needs process supervision, file watching, or high-frequency indexing with a stable protocol boundary.

Candidate sidecar modules:

- MCP lifecycle supervisor
- capability registry indexer
- config transaction engine
- file watcher
- process supervisor

The sidecar protocol must be JSON over stdio or JSON-RPC. Python remains the owner of Agent orchestration and provider semantics. The sidecar must expose explicit request and response objects, typed error payloads, and a shutdown request.

Initial protocol shape:

```json
{
  "schema_version": 1,
  "id": "request-id",
  "method": "capability.index.refresh",
  "params": {
    "workspace": "C:/Project/AITools",
    "roots": ["functions", "skills", "plugins", "config"]
  }
}
```

Responses must include the same `id`, a `schema_version`, and either `result` or `error`. Errors must include `code`, `message`, and optional `diagnostics`.

## Caching And Invalidation

Tool, skill, and plugin option discovery now has a short-lived in-process cache with explicit invalidation in `src/capabilities/discovery_cache.py`. It is intended for repeated UI schema requests, not for selected skill execution.

Required invalidation inputs before adding broader caches:

- watched roots for `functions/`, `skills/`, `plugins/`, and `config/`
- file mtime and size snapshots for manifest and declaration files
- manual refresh command exposed through CLI and WebUI
- diagnostic output showing cache age and invalidation reason

Implemented first targets:

- plugin and skill directory listings
- tool module directory listings
- MCP tool lists with TTL and manual refresh
- WebUI node config refresh as versioned delta responses
- WebUI graph topology loading with `if_version` unchanged responses

Remaining cache targets:

- optional file-watcher-driven invalidation for long-lived desktop sessions

Do not cache `SKILL.md` instruction bodies without invalidation. Existing tests rely on latest file content being loaded.

## Distribution And Versioning

Structured runtime payloads must carry schema versions at their contract boundary:

- provider feature matrix: `schema_version`
- capability registry groups: `schema_version`
- PID/runtime files: `schema_version`
- node config migrations: `schemaVersion`

Native AITools plugins support `version` in `aitools.plugin.json`, and skills support optional `version` in `SKILL.md` frontmatter. Capability descriptors expose declared versions when present.

Future package artifacts should include:

- CLI `doctor`
- docs in `docs/`
- manifest schema references
- default config examples
- migration notes for changed config schemas
