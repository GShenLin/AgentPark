# Antigravity CLI Harness

Antigravity runs as its official `agy` CLI, with its native Google login, models,
tools and conversation history. It does not use an AgentPark Provider gateway.
AgentPark starts a bounded child process for each turn and resumes the exact
conversation owned by that node. A separate gateway service is not required.

## Use

1. Open **Settings → Harness → Antigravity CLI**. Existing `agy` installations on
   PATH are detected. Windows/macOS can install a workspace-owned official binary;
   other systems can install Google's CLI themselves and add it to PATH.
2. Complete first-time sign-in in the official interactive `agy` CLI. Credentials
   remain in its native location; AgentPark does not copy or export them.
3. Refresh native models in the Harness card. Copy an exact ID into the model
   field of an **Antigravity CLI** node. The initial selection is
   `gemini-3.8-flash-medium`. Availability and quota are controlled by Google.
   Gemini 4 can be selected when it appears in the account's actual catalog.
   An unavailable model reports an error; no substitute is selected.
4. Choose a working directory or use the isolated workspace under the node's
   `.harness/antigravity/workspace`. Set native effort and execution mode if needed.

## Permissions and errors

The default preserves CLI permissions. `plan` and `accept-edits` are explicit node
options. AgentPark does not pass `--dangerously-skip-permissions` or change global
permission settings. Native headless mode cannot prompt for permission or ask an
interactive follow-up. Denied actions are surfaced as errors even when the CLI
returns exit code zero and `status: SUCCESS`. Tool failures, incomplete streams,
model/session mismatches, timeouts and cancellation are not treated as successful
turns. Native permission rules still apply when `accept-edits` is selected.

## State and lifecycle

- Node-owned resume selection lives under `.harness/antigravity/<session>/session.json`.
  Native conversation content stays in Antigravity's own storage.
- Clearing node memory removes its resume selection, so the next turn starts a
  new native conversation. It preserves workspace files and does not delete native
  conversation archives or login credentials.
- Changing the working directory requires clearing node memory or restoring the
  original directory. Model selection may change within the same conversation.
- Execution uses the documented `stream-json` input/output protocol. JSON stdin
  avoids shell quoting and Windows command-line size limits. EOF ends input after
  one turn. Cancellation/timeout terminates the child process tree.
- Settings install/upgrade jobs use the same runtime locks as other Harnesses.
  Managed downloads use `CurlHttpTransport`, official release manifests, SHA512
  verification and executable version validation before replacing the old file.
  External upgrades use `agy update`. Only the workspace-owned binary is removed
  by Uninstall; native credentials and conversations are preserved.

## Validation

Automated tests cover model/session protocol identity, partial and denied results,
tool errors, input validation, long prompts, exact conversation resume, memory reset,
catalog parsing and installation ownership/checksums. Real Windows verification uses
the detected official CLI and current account; results are recorded under ignored
`artifacts/` rather than committed credentials or native conversation storage.

Protocol reference: <https://antigravity.google/docs/cli/headless/>

Release installer reference: <https://antigravity.google/cli/install.ps1>
