# Mobile Group chat

## Behavior

Mobile graph and node lists expose explicit Group entries. Tapping one opens the same `GroupBoardPanel` and `GroupComposer` used by PC, in chat-only mode. The mobile panel shows group activity, saved replies, message recipient status, read-only member runtime status, and the shared attachment-capable composer. Group plans, member role editing, task editing, and canvas range controls stay out of the mobile chat.

Opening a group loads the latest 100 events and scrolls to the bottom. Older history remains accessible. Reading older messages is not interrupted by polling. The shared scroll handler observes both container and content geometry so viewport changes retain bottom-follow mode.

`MobileGroups.vue` owns the mobile list, active group, node status refresh, and reconnect participation. The shared panel receives explicit group data and emits close/update events rather than depending on desktop board state. `MobileWorkspace.vue` remains an integration point; new group behavior is separated because the existing workspace file already exceeds 400 lines.

The `mobile_group` URL parameter works alongside `mobile_graph` for cloud Board restoration. Node navigation or leaving the graph clears stale group destinations. Reconnect retains the active panel and draft; the composer disables submissions while the session is unavailable.

## Verification (2026-09-27)

- Vue/TypeScript check and production build passed.
- Mobile location and group session tests passed, including saved group destination handling.
- Real Chrome in mobile emulation at 430 × 900 and 375 × 812: both entry points open the shared panel, management controls are absent, member state is visible, latest history opens at the bottom, polling preserves reading position, and width changes keep bottom-follow mode.
- In an isolated graph with two paused agents and 125 seeded history replies, a real file upload and broadcast persisted successfully. Both recipient states and the attachment appeared in mobile chat; PC displayed the same broadcast and retained role/task management controls.
- Browser checks produced no JavaScript page errors. Results/screenshots are in `.runtime/mobile-group/` (local diagnostic artifacts).
- This round tests frontend routing, rendering, upload, and broadcast persistence. It does not claim physical handset, cloud relay, or new model execution validation; the fixture agents were paused.

## Cloud delivery correction (2026-09-27 23:30 CST)

The initial release updated the local service only. The user's phone loads the independently hosted frontend at `https://203.0.113.10`, which still referenced `index-B9Xn7pIO.js`; the local build referenced `index-BkmAOPKA.js`. The real `beaconfall-team` group existed in the local API, so the missing mobile Group entry was a frontend deployment mismatch.

Deployed the current `webui/dist` to the cloud frontend using a verified archive and the existing atomic install/rollback routine. All 67 manifest files verified; existing fingerprinted assets were retained for open clients. Backup: `/opt/agentpark-coordinator/backups/webui-20260927T153024Z`. No Agent or signaling restart was required. Public HTTPS JavaScript matched the local build (SHA-256 `526d1cfa87eca4936e46806c970ee7afa9385b0e9c53c4e8ad731224baa723fc`).

Additional actual Chrome mobile-emulation verification through the public cloud Board and real device connection passed: `Group 1` appears in `beaconfall-team`, clicking opens the shared chat at the bottom, Engineer/Producer states and history are visible, broadcast composer is present, management controls are absent, and reloading restores the same group directly. No messages were sent to the productive agents. Browser errors: none. Evidence: `.runtime/mobile-group/cloud-results.json`, `cloud-entry.png`, and `cloud-chat.png`. Physical handset acceptance remains user-side.
