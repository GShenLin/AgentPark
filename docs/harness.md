# Harness runtimes

AgentPark separates the graph node boundary, Harness runtime and Provider/Model binding.
Settings → Harness manages six independently registered runtimes:

| Harness | Node type | Transport | Conversation storage |
| --- | --- | --- | --- |
| Codex | `codex_node` | app-server | Existing native Codex thread pointer |
| Claude Code | `claude_node` | Claude Agent SDK | Existing native Claude session pointer |
| OpenClaw | `openclaw_node` | `agent --local --json` | Isolated OpenClaw state directory |
| DeepSeek Harness | `deepseek_harness_node` | ACP JSON-RPC over stdio | ACP session ID and isolated DSH home |
| Pi | `pi_node` | `--print --mode json` | Explicit Pi session JSONL file |
| Hermes Agent | `hermes_agent_node` | Python AIAgent SDK in an isolated subprocess | Atomic conversation snapshot and isolated Hermes home |

## Use

1. Open Settings → Harness and check the installed runtimes.
2. Install the desired Harness, or use a detected external installation.
3. Create its node and select a conversational Provider, then one of that Provider's allowed models.
4. Set the working directory and Harness-specific options, then send a message.

An empty model uses the first configured model. An explicit model outside the Provider's allow-list fails.
Node instances may select different models from the same Provider concurrently.
Provider credentials stay behind AgentPark's local gateways. CLI configuration contains only a short-lived local lease;
it never contains the upstream API key. Authentication and protocol conversion continue to use AgentPark's existing
Responses, Chat Completions, Anthropic and Gemini dispatchers.

## Ownership and installation

AgentPark installs the five JavaScript runtimes into `.runtime/harnesses/<id>/node_modules` with npm.
New installations are workspace scoped. Upgrades replace the active installation in place, including external npm
installations; their local/global scope and original prefix are preserved. The prefix is derived from the detected
launcher and validated against its package manifest, rather than taken from npm's current default configuration.
External installations cannot be uninstalled from AgentPark. A managed installation takes precedence over an external command unless a Codex/Claude
node explicitly names a different executable.

Installation, upgrade and removal run as background jobs. Errors and npm output are returned to the settings page; a successful
install is followed by an executable version probe. npm engine constraints are enforced, so an incompatible Node.js
version is an installation failure rather than an apparently successful setup. Install uses the registry's current
`latest` tag and saves the resolved version exactly.

Opening Harness settings or choosing **Check for updates** compares the installed package's SemVer version with
the npm registry's `latest` tag. Registry failures appear separately from runtime health, and can be retried with
another check. Prerelease precedence is respected; a locally newer release is never offered a downgrade.
**Upgrade** appears only when a newer release is available. The job rechecks the version under the installation
lock, installs the exact resolved release with engine constraints enforced, and verifies the package version and
executable before reporting success. **Reinstall** remains available when no update is offered.
Both managed and external npm installations use **Upgrade**. External updates do not create a workspace copy or
change installation source. Unknown native installers, linked development packages and unsupported layouts display
an explicit reason and require their original installer; they never fall back to installing a second copy.
Permissions and file-lock failures are reported by the job. Session data is preserved.
Nodes with an explicitly configured executable continue to use it; settings manages the detected default installation.

Hermes Agent uses the official NousResearch GitHub **stable release** instead of an npm package or an unrelated
PyPI name. Its calendar release tag and Python package version are checked separately. Install requires Git and creates
`.runtime/harnesses/hermes_agent/source` plus an isolated Python 3.12 `.venv` using uv. If uv is missing, a private
bootstrap environment supplies it; AgentPark's interpreter and dependencies are not modified. The SDK runtime is
imported to verify the installation. This path was tested against release `v2026.9.14` / Python package `0.21.3`.
Upgrades retain the existing source directory and Python environment. External official Git/venv installations are
located through their launcher and upgraded in place. Dirty source trees and local commits on a tracking branch
are rejected; unfamiliar installers require their own update workflow. Managed uninstall removes only the installation,
preserving node conversation snapshots and Hermes homes.

Active turns and installation operations exclude each other through OS-backed shared/exclusive file locks, including
spawned node workers. Concurrent node turns may hold shared locks. Idle native clients in the backend close before
replacing their installation. Coordination is local to the host and is not a distributed installation service.

CLI conversation identity is stored in `<node-directory>/.harness/<id>/current-session.json`, independently of
Provider and Model. Switching either keeps the same native conversation and routes the next turn through the new
binding. Runtime configuration changes do not implicitly create a conversation. On first use after upgrading,
the exact existing binding directory is adopted in place, preserving native IDs and history. If historical
directories exist but none matches, restore the previous configuration once to adopt it; the runtime fails
explicitly instead of guessing another conversation or starting an empty one. Uninstall preserves session data.
Codex/Claude retain their existing native session browser and IDs.

For OpenClaw, Pi, DeepSeek Harness and Hermes Agent, an empty working directory creates and uses
`<node-directory>/.harness/<id>/workspace/`. It never defaults to the AgentPark source directory.
An explicitly selected working directory must already exist and is passed through unchanged. Native runtimes own
their prompt, tool and skill discovery; AgentPark does not copy its project instructions or skills into the node's
workspace. Changing a previously implicit host workspace to the node workspace starts a new native conversation,
preserving the old state on disk without replaying its host-project context.

## Boundaries

- `src/harness/contracts.py`: immutable descriptors, execution context, adapter protocol and result.
- `src/harness/registry.py`: descriptors and lazy adapter construction.
- `src/harness/node.py`: Provider/Model schema, graph envelope, channel metadata, cancellation/installation lease.
- `src/harness/provider_binding.py`: allowed-model validation without putting credentials in a public binding.
- `src/harness/responses_gateway.py`: shared Responses-facing local gateway, with a model pinned per lease.
- `src/harness/install_manager.py`, `jobs.py`: package ownership, executable resolution, lifecycle and background jobs.
- `src/harness/installation.py`: npm installation location, scope and package entry validation.
- `src/harness/hermes_installation.py`, `hermes_release.py`: isolated Python lifecycle and official release lookup.
- `src/harness/updates.py`, `npm.py`: registry queries, explicit CLI version formats, SemVer comparison and npm resolution.
- `src/harness/process.py`, `acp_client.py`: bounded subprocess IO, cancellation and strict ACP request handling.
- `src/harness/adapters/`: native runtime orchestration and protocol-specific event parsing.
- `src/web_backend/harness_api.py`: owner-only management routes and closed request schema.

The adapter boundary is a complete graph turn, not a fabricated universal session protocol. Codex app-server and
Claude SDK continue to own persistent clients, permissions and their existing event projections. Pi and OpenClaw own
their on-disk histories; DeepSeek uses ACP `session/new`, `session/resume`, `session/set_config_option`, `session/prompt`
and `session/close`. Unsupported client permission requests fail explicitly. No adapter substitutes another runtime.

Hermes runs its real `AIAgent` SDK in its own interpreter. `hermes_runner.py` owns only the process wire protocol and
atomic conversation snapshot; Hermes owns inference, tools, memory and skill discovery. AgentPark supplies the current
model and temporary local Responses gateway lease on every turn, so resumed sessions never reuse an expired endpoint.
Text, reasoning and stable-ID tool callbacks project into the same live node event protocol. Failed/interrupted or
incomplete SDK results fail the node and do not overwrite the successful conversation snapshot. Background review is
disabled for this per-turn subprocess lifecycle; the adapter does not run a Hermes messaging gateway or cron daemon.

The existing large SettingsPage remains orchestration-only for this feature: UI state, polling and card rendering
are in the new HarnessSettingsPanel. Existing large runtime modules are retained where their responsibility is
unchanged; new Harness modules stay below 400 lines.

## Current limits

- Pi, OpenClaw, DeepSeek Harness and Hermes Agent require developer access. They do not implement AgentPark's enforced read-only
  sandbox. Codex and Claude preserve their existing read-only/plan mapping for nondevelopers.
- OpenClaw's local JSON CLI returns the final payload, so it does not expose live tool or token deltas here.
  Pi and DeepSeek project text, reasoning and tool lifecycle events into AgentPark's live protocol.
- DeepSeek uses the **published ACP interface**. The repository's newer headless `--json` documentation was ahead
  of the tested npm release and is not the adapter contract.
- The native session picker remains specific to Codex and Claude. Other Harnesses automatically resume their
  node-specific histories; browsing/importing arbitrary external sessions is not implemented.
- Inputs follow the existing node envelope-to-text/resource representation. New Harness adapters do not claim
  native audio/video ingestion or binary assistant output.
- Node.js/npm must already be available on the backend host. Tested OpenClaw 2026.9.4 requires
  `>=24.16.0 <25 || >=26.1.0`; the development host has since been upgraded to Node 24.19.0 LTS and its OpenClaw
  version probe passed. The original integration tests used an isolated temporary Node 26.1.0.

## Verification

Unit/integration coverage includes per-lease model isolation and revocation, unsupported model rejection,
process cancellation/timeouts, strict native output parsing, workspace package ownership, active-turn exclusion,
owner-only management routes and Provider/Model selection for all six node types.
Update coverage includes SemVer/prerelease ordering, registry failure isolation, stale upgrade rejection,
active-turn exclusion, exact-version verification and in-place external upgrades. Frontend tests exercise
the check/upgrade/poll/refresh flow, disabled actions while running, and failed-job feedback.

`tests/test_harness_upgrade_smoke.py` exercises real install → check → upgrade → verify → uninstall cycles in a
temporary workspace and a temporary external npm global prefix. Set `AGENTPARK_TEST_PI_UPGRADE_FROM` to an older
published Pi version (tested with `0.85.0`) to enable them. They verify session preservation and, for external upgrades,
an unchanged executable path/source and absence of a workspace copy. Existing system/workspace installations are untouched.

`tests/test_harness_cli_smoke.py` runs real CLIs against a local HTTP model stub. It verifies four consecutive turns
across a model switch, a Provider switch and a switch back, checking prior user/assistant history, selected-model
routing, Provider authentication and absence of upstream credentials in generated configs.
Set `AGENTPARK_TEST_PI_ENTRY`, `AGENTPARK_TEST_DSH_ENTRY`, or `AGENTPARK_TEST_OPENCLAW_ENTRY` to an installed JS entry
point to enable each test. The test invokes `node` from PATH. It makes no paid model requests.
For Hermes, set `AGENTPARK_TEST_HERMES_PYTHON` to its environment's Python interpreter instead. The same test verifies
conversation continuity across binding changes and workspace isolation; `test_hermes_runtime_smoke.py` exercises an actual
file-read tool call and live event projection. `AGENTPARK_TEST_HERMES_INSTALL=1` enables the real official Git/Python
install → check → in-place upgrade → uninstall test in a temporary workspace.

Verified CLI releases: Pi 0.85.1, DeepSeek CLI 0.1.5-rc.1 (resolved ACP packages 0.1.5-rc.2), OpenClaw 2026.9.4.
The existing real Codex app-server test also passed against locally installed Codex 0.145.0, including a tool call.
Claude SDK behavior is covered with controlled SDK fixtures; real Claude model execution was not part of this run.

## Upstream references

- [OpenClaw local agent CLI](https://docs.openclaw.ai/cli/agent)
- [Pi coding agent CLI](https://github.com/earendil-works/pi/tree/main/packages/coding-agent)
- [Pi custom model configuration](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)
- [DeepSeek Harness](https://github.com/deepseek-ai/deepseek-harness)
- [DeepSeek ACP implementation](https://github.com/deepseek-ai/deepseek-harness/tree/master/packages/acp/acp)
- [Hermes Agent release](https://github.com/NousResearch/hermes-agent/releases/tag/v2026.9.14)
- [Hermes Python SDK](https://github.com/NousResearch/hermes-agent/blob/v2026.9.14/run_agent.py)

Published npm package contents, rather than unshipped repository features, determine the implemented command line.
