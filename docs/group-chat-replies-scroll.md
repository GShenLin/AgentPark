# Group conversation replies and scroll — 2026-09-27

The group panel now opens the latest 100 events at the bottom, supports loading earlier pages without moving the reading position, follows new content only when the reader is at the bottom, and provides a return-to-latest button. The event endpoint supports explicit latest/before pagination, preserving the incremental cursor API used by agents.

User broadcasts display per-member waiting, processing, completed, cancelled or failure state. Execution start is persisted separately from outbox delivery state. Final user-facing responses are recorded as read-only reply events after node history persistence; these events have no notification recipients and cannot trigger peer reply loops. Existing private-group checks and revoked-membership protections remain in place.

A running group notification can consume new same-access-role user followups through the existing agent mid-turn input callback. Peer messages are not injected by this path. Newly consumed inputs are included in completion tracking and reply association. This occurs at provider continuation/tool boundaries; an already running remote model request is not forcibly cancelled.

Verification:
- 72 backend tests passed across groups, delivery, API, lifecycle, board reads, node context and cancellation.
- Additional node-context test confirms group followups enter the provider user-input callback.
- Frontend type check and canonical production build passed.
- Actual GPT_Official / gpt-6-astra broadcast to two isolated nodes: both returned exactly GROUP-REPLY-OK; two group reply events, two completed original deliveries, no reply notifications.
- Installed Chrome: latest 100 of 229 events, initial/reopened bottom, historical polling stability, return-to-latest, older pagination, both actual replies and member completion labels, 800px desktop width, arrival while following and arrival while reading history. No page script errors. Mobile workspace uses a separate entry point and was not verified here.
- Evidence: .runtime/group-chat/live-results.json and chrome-results.json. Test graph cleaned through normal API.
- The two existing answers to user event #133 were recovered from node message records using the exact notification trace identity and recorded as read-only group replies. Source text and completion times retained; no model rerun or delivery created.
- Canonical restart worker 43272, new PID 46020, instance 12ce932d0eed40efb9ecc961064d97ff; no active tasks when restarted.

Responsibility boundaries: group delivery owns followup selection/result publication, repository owns cursor queries, the small scroll composable owns scrolling, and GroupMessageStatus owns recipient labels. Existing large node execution code receives only the integration calls rather than accumulating UI/history logic.
