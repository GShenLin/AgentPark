# Windows desktop tray

The normal Windows server entry point starts the existing Electron desktop host
after Uvicorn binds its listener. The host owns a single tray per server origin;
closing all node windows leaves the tray alive. A server disconnect closes its
tray; restarting the server starts a new host connection. Browser-only development
servers and non-Windows servers do not start a tray.

## Menu

- **Working**: all nodes whose canonical in-memory runtime state is `working`.
  This uses the same state as the board (including an active clock node), not
  whether a node window is open. Finished/stopped nodes disappear on next opening.
- **Recent**: at most ten nodes ordered by successful conversation append time.
  A node may appear in both sections. Every right-click requests a fresh snapshot.
  Clicking an item opens its node window or focuses the already-open window.
- **NewNode**: opens the local WebUI with `?desktop_action=new-node`. After bootstrap,
  the current startup graph and node catalog are ready, the existing creation menu
  opens automatically. Choose a type/profile and finish the existing creation form.
  The URL action is consumed once, so reload does not reopen it.
- Open AgentPark, show/hide the existing Companion console, checkpoint and restart,
  or exit the entire workspace through the existing shutdown path.

## Boundaries

`node_conversation_activity.py` writes `.conversation-activity.json` beside node
history, inside the existing memory transaction, only after history append succeeds.
Metadata contains a commit timestamp, not a stored node name; renames/moves follow
the node folder and deletions disappear from the projection. Existing history does
not get guessed timestamps: a node enters Recent on its next conversation append.
Configuration edits, window geometry, and opening a node do not change recency.

`desktop_tray_snapshot.py` combines these timestamps with canonical config/runtime
state. It does not scan file modification times or duplicate the runtime registry.
Malformed metadata/configuration is reported as a menu load error, not an empty list.

`desktop_tray_api.py` is a loopback-only WebSocket command boundary authenticated
by a per-server capability in the first frame. Remote/cross-origin callers are
rejected; commands have a discriminated, extra-forbidden schema. Electron performs
no direct HTTP API requests. It renders menus and delegates business operations.
Desktop host logs are in `.runtime/node-windows/host.log`.

New tray responsibilities are separate files. The existing large history store only
gains the post-commit hook; a future split should separate append/replace/delete/read
operations without moving their transaction or error boundary.

## Verification

```powershell
python -m pytest tests/test_desktop_tray.py tests/test_desktop_tray_protocol.py tests/test_node_window_api.py tests/test_http_transport_boundary.py
npm --prefix desktop/node-window test
npm --prefix webui run test -- tests/desktopNodeCreation.test.ts
npm --prefix webui run build
```
