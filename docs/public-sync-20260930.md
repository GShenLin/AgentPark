# Public feature synchronization — 2026-09-30

Application changes from source snapshot `ed5719c1` through
`d558f6525514a5829c972c48e9bd60b657c751cf` are applied on top of public
`main` at `719520c`. The existing public Git history and README opening are
preserved; private source history is not imported.

## Included updates

- Agent Groups: membership, directed collaboration, task planning, delivery,
  attachments, notifications, board frames, and mobile group conversations.
- Skill management: multiple sources, folder organization, deferred activation,
  and migration of bundled skills to `.agents/skills`.
- Node synchronization: device/cloud transport, incremental synchronization,
  permissions, and settings controls.
- Explicit import of the current device's Codex login into the matching
  AgentPark account, together with its backend and UI contracts.
- Unified project HTTP transport, provider parameter mapping, background
  compaction, console sessions, startup certificate trust, and harness fixes.
- Chat appearance, uncapped Live text, memory details, board/portal retention,
  mobile scrolling, and settings layout improvements.

## Public configuration

Local provider files, account bindings, authentication stores, runtime state,
conversation histories, generated deployment certificates, private attachments,
personal instructions, and research reports are excluded. Public agent examples
remain available. Conversation and long-term memory settings now select the
bundled `DouBao` agent profile; configure that profile's provider before use.
Deployment examples continue to use the reserved address `203.0.113.10`.
Generate your own trust material for your deployment.

The Windows certificate installer tests generate temporary certificates and
use an in-memory store, so they require neither deployment certificates nor
changes to the machine's trusted certificate store.

## Validation

- Frontend: 55 test files, 252 tests passed.
- Frontend type check and production build passed; Vite reported the existing
  large-chunk advisory.
- Focused backend validation: 285 tests passed and 1 skipped across 26 modules.
  The three certificate installer tests initially required omitted deployment
  files; after replacing that dependency with generated test certificates,
  all 3 passed. Combined result: 288 passed, 1 skipped.
- Coverage includes the HTTP transport boundary and integration, Groups,
  Skill management/activation, node synchronization, credential import,
  console sessions, memory configuration, and workspace bootstrap.
- Staged whitespace and excluded-path checks passed.

This is focused regression validation, not a full backend suite or a live
deployment of the public snapshot.
