# Linux Merge Acceptance

This repository carries Linux-port changes on top of an upstream Windows-first
AgentPark codebase. After pulling or rebasing upstream changes, run the Linux
acceptance script before treating the merge as complete.

## Commands

Fast local gate:

```sh
scripts/acceptance_linux.sh --quick
```

Full local gate:

```sh
scripts/acceptance_linux.sh --full
```

Skip the WebUI build when only backend contracts changed:

```sh
AGENTPARK_ACCEPTANCE_SKIP_FRONTEND_BUILD=1 scripts/acceptance_linux.sh --full
```

Skip provider factory construction only when local provider credentials are not
available:

```sh
scripts/acceptance_linux.sh --skip-provider-factory
```

## What It Checks

- unresolved git conflicts and committed conflict markers
- JSON validity for local runtime configuration files
- provider type compatibility with `src.providers.create_agent`
- backend import health
- focused provider, config, Responses, memory, mobile, skills, MCP, plugin, and
  tool protocol tests
- optional WebUI production build
- required Linux shell scripts are executable

The checks are intentionally local and offline. They should not send real model
requests or depend on upstream provider availability.

## What It Cannot Guarantee

This gate does not make a large upstream refactor conflict-free. It cannot know
whether a manually resolved conflict preserved every intended behavior.

Its job is to make common Linux-port regressions visible immediately after a
merge: unsupported provider types, Windows-only command residue, broken config
contracts, frontend build failures, and broken extension loaders.

When upstream changes are structurally large, resolve the merge first, then run
`--quick`. If it passes, run `--full`. If `--full` fails, classify the failure as
one of these before patching:

- merge conflict residue
- provider/config contract mismatch
- platform/runtime issue
- frontend build issue
- skills, MCP, plugin, tool, memory, or mobile API contract breakage
- external provider outage, if and only if a real provider request was made

Do not mask those failures with permissive fallbacks. Fix the owning contract or
module directly.
