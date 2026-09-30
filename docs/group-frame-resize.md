# Group frame resize — 2026-09-27

New group frames follow the outer grid-cell boundary of selected members, including cards spanning multiple cells. The outline is painted outside that rectangle; the group label sits above it.

Drag any edge or corner to resize. Preview snaps to the grid, minimum one cell, no negative coordinates. Escape, pointer cancellation, window blur, graph switch, or connection loss cancels an unfinished drag. Existing historical frames snap to the grid when resized.

On release, the server reads authoritative node positions under the graph layout lock. Membership uses the same half-open card-center rule as node dragging. A single database transaction applies the bounds, membership index, events, notification recipients, and task-owner releases. Existing member roles survive; unfinished tasks belonging to departing members become blocked and unassigned. Empty groups remain resizeable. Overlap, stale revisions, or hidden nodes reject the operation without a partial write. Pure frame changes do not wake agents.

Verification:
- Frontend type check and production build passed.
- 9 frontend geometry/session tests passed.
- 39 backend group/API/delivery tests passed, including resize membership, task release, role preservation, empty groups, stale update rejection, overlap rollback, invalid grid, and private-node access.
- Real installed Chrome, isolated paused test graph: marquee + G full-cell creation; right-edge expansion/shrink; left/top/bottom edges; two opposite corners; Escape; reload persistence; actual 100% to 90% zoom and subsequent resize; overlap rejection; no browser script errors.
- Evidence: `.runtime/group-resize/results.json`, `additional-results.json`, `chrome-resize.png`, `verified.png`. The temporary verification graph was deleted through the normal API after tests.
- Current Beaconfall Team Group 1 was aligned to x=300, y=320, width=900, height=320 with the original Engineer/Producer members preserved.
- Canonical restart worker 44808: built frontend and started PID 37264, instance d3e0e1032c864d42aae3e9a812e4ba37. Restart checkpoint had zero active nodes.
