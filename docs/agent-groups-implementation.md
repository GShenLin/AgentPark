# Agent groups: implementation and acceptance

## Requested outcome

Groups are persistent task boards, not agents. Marquee-select agents and press G
to group; select an existing group's members and press G again to dissolve it.
The Graph panel lists groups and can dissolve them without deleting agents.
A rectangular canvas frame encloses members. Dropping an agent into/out of that
frame joins/leaves the group. Clicking empty space inside opens the task board.
The board shows the plan, tasks, members' live work, and a message composer.
User messages broadcast to the members. Members receive group context and tools
to communicate, create/claim/update tasks, and notify teammates of changes.

## Boundaries and contracts

- `src/agent_groups`: validated contracts, transactional state, event log and
  delivery outbox; independent of web transport and provider SDKs.
- Web API: checks graph/node visibility and membership, projects runtime status,
  delegates mutations to the group store, publishes changes to the existing app
  event stream, and delivers queued group events to the existing node queue.
- Agent integration: binds authenticated graph/node identity at tool registration;
  tool callers cannot supply another actor. Membership is rechecked on every call.
- Frontend: typed API/state, group geometry and selection behavior, canvas frames,
  shared board panel, Graph group list. Existing node selection/drag stays intact.
- One agent belongs to at most one group within its graph. Moving between groups
  is atomic. Group deletion dissolves membership but never deletes agents.
- Persist groups separately from graph presentation configuration so a stale
  canvas save cannot overwrite agent-authored task/message updates.
- Store mutations and recipient outbox entries in one SQLite transaction. Use
  existing node-queue idempotency keys for retried delivery. Show delivery errors;
  do not silently discard events or claim messages were delivered on enqueue failure.
- Task updates use revisions; claiming an already-owned task fails explicitly.
  Dependencies cannot cycle. Completed tasks require an evidence note. Task state
  changes and messages notify teammates, excluding the author. Runtime status is
  projected, not broadcast as a new task event on every heartbeat.
- Notifications carry an event ID and are informational unless action is needed.
  Agents must not acknowledge every notification or create acknowledgement loops.
- Group membership/permissions are rechecked before delivery and at execution.
  A member that leaves loses access to subsequent group work and communication.

## Delivery stages (evidence required before completion)

1. Transactional contracts/store; concurrent claims, event/outbox, membership and
   persistence tests.
2. Authorized APIs, event delivery, automatic group tools/context; real two-agent
   conversation and shared task updates across restart.
3. G toggle, frames, drag membership, Group list, task board/composer; actual
   browser interaction and focused regression checks.
4. Dedicated GPT_Official test graph with role-specific agents, shared project,
   task ownership and integration/QA cycles. Preserve existing user graphs.
5. Produce and play a complete game through the group workflow. Prove actual
   agent communication, task execution, source edits, integration, and fixes.
   A task board full of 'done' labels alone is not completion evidence.

## Game trial and verification

Working title: Beaconfall. A desktop-browser adventure with a complete narrative
arc, distinct levels, character progression, encounters/puzzles, save/load,
onboarding, failure/retry, and an ending. Target 45–60 minutes for a first playthrough;
this is a design target until gameplay evidence supports it. No artificial waiting
or repeated filler solely to meet duration.

Planned roles: producer/integrator, gameplay programmer, level/puzzle designer,
narrative/UI designer, and QA. All may use GPT_Official for the authorized trial;
each has clear file ownership and communicates via the implemented group tools.
QA reports reproducible issues on the shared task board; owners fix and QA retests.

Acceptance evidence must include grouping/dissolution, joining/leaving, live task
claims, private and broadcast messages, notification delivery, restart persistence,
different skills/providers remaining independently configured, game source and
launch instructions, completed gameplay paths, progression/save tests, measured
playtime evidence, and disclosed remaining limitations. Keep the goal active while
any explicit requested capability or the verified game outcome remains incomplete.

## Current acceptance boundary

See [validation record](agent-groups-validation.md) for dated runtime evidence,
failure injections, actual team work and game playthroughs. It is a historical
record; later entries supersede earlier pending/deployed states.
The [requirement-by-requirement audit](agent-groups-acceptance.md) separates proven
capabilities, game content evidence and remaining release work.

The complete objective has passed the final requirement audit. UI grouping and game production have real
execution evidence. Provider recovery, paged board reads and node lifecycle
integration have post-deploy acceptance evidence. First-play findings and final
reset/Anchor follow-up have independent acceptance (26 Node tests and five Chrome
scripts); final README/PLAN reconciliation is complete at group event249. Human playtime must not be
inferred from AI operation time.
