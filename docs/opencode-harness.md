# OpenCode CLI Harness

AgentPark manages the official OpenCode v2 CLI (`@opencode/cli`) in
Settings → Harness. Install, version checks, upgrades and uninstall use the same
installation jobs and active-runtime leases as other Harnesses. A node starts
`opencode acp` as an owned child; a separate terminal or shared OpenCode server
is not needed. The adapter requires ACP v1 with session resume and close.

## Use

1. Open Settings → Harness → OpenCode CLI and install it if needed.
2. Use **View / refresh native models** to read the installed CLI's model list.
3. Create an **OpenCode CLI** node. Its default model is
   `opencode/deepseek-v4.1-flash-free`, and its default native agent is `build`.
4. Set a working directory, or leave it empty for the node-owned workspace.
   Send messages through the node normally. Set `native_agent` to `plan` for
   OpenCode's planning agent. An optional `native_effort` must match an effort
   advertised by the selected model. Model, Agent and reasoning effort are native
   dropdowns populated through ACP. Changing model/Agent resets effort to the
   model default and reloads available choices. Discovery uses a temporary database
   and sends no prompt; it does not modify the node's conversation. Failed discovery
   is shown with a retry button, and unavailable saved values remain visible.

The node's `native_model` is an OpenCode `provider/model` identifier. It does not
select an AgentPark Provider, proxy credentials, or call the free inference API
directly. OpenCode uses its own existing user configuration and login. Additional
provider login is performed with the official CLI's `auth login`; the Harness
panel does not collect API keys. Free model availability and quotas are controlled
by OpenCode. Missing models fail before inference; there is no paid fallback.

## Runtime boundaries

- `nodes/opencode_node.py` defines the graph entry and native config schema.
- `src/harness/adapters/opencode_config.py` validates the request and exact ACP
  config options, including grouped model choices.
- `src/harness/adapters/opencode.py` owns negotiation, model/agent selection,
  prompt execution and session resume. `OPENCODE_DB` points to a node-owned SQLite
  database under `.harness/opencode/<session>/sessions.db`; credentials remain in
  OpenCode's own user locations.
- `src/harness/execution.py` serializes runs for a conversation and records native
  tool events. It is shared with provider-backed CLI adapters without requiring a
  provider gateway for OpenCode.
- `src/harness/acp_events.py` projects strict ACP text, thought and partial tool
  lifecycle events for both OpenCode and MiniMax. It retains rendered tool content
  even when `rawOutput` contains only metadata.
- `src/harness/opencode_catalog.py` runs `models --standalone`; the owner-only
  `/api/harnesses/opencode/models` endpoint returns those exact identifiers.

Changing model or instruction keeps the conversation. Changing the working
directory of an existing session requires restoring the original directory or
clearing the node's memory. Memory reset removes the node-owned database and
session selection, preserving workspace files and global OpenCode credentials.
Normal completion closes the ACP session and child. Timeout/cancellation also
closes the child, force-terminating its process tree if it does not exit promptly.

The existing ACP client does not handle interactive permission dialogs: it
explicitly cancels a requested approval and reports an error. OpenCode's normal
native permission rules apply; the adapter does not auto-approve or disable them.
Native host tools require AgentPark developer access. ACP questions/forms and
image response blocks are not advertised as supported client capabilities.

## Verification

On 2026-10-16, managed OpenCode **2.0.31** ran successfully on Windows. Its native
catalog listed ten models, including `opencode/deepseek-v4.1-flash-free`. A real
ACP prompt returned `OPENCODE_OK` without additional login. Separate adapter runs
returned `FIRST_OK`, recalled `PARK-731` after restarting the CLI, then wrote and
read `proof.txt` and returned `TOOL_OK`; AgentPark received matching start/end
events for both tools. These results establish availability at test time, not a
permanent free entitlement.

Live WebUI acceptance also passed after restarting AgentPark: the Harness card
reported managed 2.0.31, refreshing its model list returned the native catalog,
and the create-node dialog retained the free default without an AgentPark
Provider selector. An **OpenCode CLI** node was created on the `default` graph;
a message sent through its chat window completed successfully. The node remains
available for use. Screenshots and browser evidence are in local `artifacts/`.

Validation: 105 backend tests passed, one environment-dependent test skipped;
21 frontend regression tests passed; the production WebUI build and
`git diff --check` passed.

`tests/test_opencode_harness.py` covers native config, exact model selection,
session ownership/resume, cleanup, tool output, catalog validation and API access.
Shared Harness/ACP/MiniMax regression tests protect the reused execution path.

Official references: [installation](https://opencode.ai/v2/docs/),
[ACP contract](https://opencode.ai/v2/docs/cli/acp/),
[model availability](https://opencode.ai/v2/docs/console/models/).
