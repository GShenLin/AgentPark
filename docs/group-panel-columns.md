# Group tasks and activity columns

Desktop Group panels show tasks on the left and activity on the right, with
independent scrolling. Plans and member details remain available in a folded
section below tasks. At widths up to 720 px, the same panel uses Tasks / Activity
tabs, initially showing Activity; mobile still omits member/plan management.

Each task owns its inline editor and draft. A group refresh does not overwrite
an open draft; saves retain the existing revision conflict checks and queue
feedback. Saving, cancelling, errors and dependency options stay with that task.

Completed tasks are collected in a collapsed Archive section, sorted by latest
update. This is a view of existing persisted `done` tasks, not a second lifecycle
state. Evidence, dependencies, IDs and history are retained. Reopening through
the ordinary status editor returns the task to the active list, subject to the
existing dependency rules. Opening or folding the archive creates no event or
agent notification.

Activity is rendered in descending sequence order. Initial opening and sending
show the newest events at the top. Older pages append below. During incremental
updates, the visible event and its offset anchor the reading position; a Back to
Latest button explicitly returns to the top. The former bottom-following resize
observer is removed because it could override manual scrolling during layout.

## Verification (2026-09-28)

- Production type check/build passed; six existing feedback/session tests passed.
- Actual Chrome with an isolated paused Worker and 14 tasks / 105 shared updates:
  verified column geometry, independent scrolling, inline editing and persisted
  save, completed-task folding, archived evidence review, reopening, descending
  events, historical pagination, live update reading position and mobile tabs.
- Measured reading anchor movement on insertion was less than one CSS pixel.
- Reload retained task edits/reopening and restored the collapsed archive view.
  No page errors. The fixture was deleted through the application API.
- Local artifacts: `.runtime/group-columns-result.json`,
  `.runtime/group-columns-desktop.png`, `.runtime/group-columns-mobile.png`.
- Local and cloud frontend assets: `index-BtyHMATz.js`, `index-BzRSKB76.css`.
  Cloud deployment verified 67 files and retained backup
  `/opt/agentpark-coordinator/backups/webui-20260928T112336Z`.
- Public cloud mobile Chrome on the real BBQ group: verified descending activity,
  initial top position, task tab, collapsed archive and inline archive review.
  No writes were sent, and no page errors occurred. Screenshot:
  `.runtime/group-columns-cloud-mobile.png`.
- No backend change or restart is needed for this layout and archive view.
