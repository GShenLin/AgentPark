# G grouping must not start agents — 2026-09-27

Root cause: event persistence defaulted to notifying every member. Creating a group and dissolving a group therefore generated durable outbox deliveries; the delivery service enqueued them as group_notice work. Dissolution cancelled older pending notices, then created another notification for former members. Repeated G presses thus produced repeated independent executions, not duplicate key handling.

Changes:
- Event persistence now requires an explicit recipient list; audit/history alone has no implicit execution side effect.
- Creation, dissolution, membership/role/identity changes, restoration and geometry-only edits record history without waking nodes. Name-only plan changes are also audit-only.
- Explicit messages, objective edits and task work retain their intended recipients.
- Store schema v2 cancels pending structural deliveries from v1 while preserving events, past results and real work. Stale queue references resolve empty and the existing execution boundary returns before the model is invoked.
- A regression discovered during lifecycle testing was also fixed: renaming a node preserves the message idempotency serialization for empty attachment lists.

Validation:
- 59 group, delivery, API, node lifecycle and board-read tests passed.
- Added a 20-cycle group/dissolve regression with no queued work followed by a broadcast that reaches both recipients.
- Migration test confirms old queued structural references resolve empty and real broadcast deliveries remain intact.
- Installed Chrome: 20 actual marquee-selection / G create / G dissolve cycles. Database: 20 group_created + 20 group_dissolved audit records, 0 delivery rows. Runtime: 0 active nodes, 0 ready pending items. Browser errors: 0.
- Local graph stores upgraded to v2 with 0 pending creation/dissolution/membership notices.
- Test graph removed through the normal API. Evidence is in .runtime/group-toggle/.
- Canonical restart worker 38712 built and started PID 44100, instance 8cc7b97a6d184a2a9ced73ca1936560d. No active node work at restart.
