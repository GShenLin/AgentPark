# Computer Use

Select the `computer-use` skill and a provider that supports tools and image input.
The model initially sees only the skill description, current state, and activation/closing tools.
`activate_skill("computer-use")` exposes desktop tools and instructions across messages and restarts.
`deactivate_skill("computer-use")` removes them when desktop work is done. Shared tools remain
while another active skill or explicit node configuration needs them. Clearing conversation history
resets activation. Reading this document does not activate tools. Skill-owned MCP tools follow
the same lifecycle; current runtime state takes precedence over historical summaries.

## Observe and act

1. `list_apps` / `list_windows`: discover applications and select an exact window.
2. `get_window` reacquires its identity; `activate_window` restores/focuses it and returns a fresh state.
3. `get_window_state`: inspect the PNG screenshot and, with `include_text=true`,
   UI Automation controls, focus, supported control values and selected text.
4. Call one of `click`, `drag`, `scroll`, `press_key`, `type_text`, `set_value`,
   or `perform_secondary_action`, passing the returned window and observation ID.
5. Inspect the fresh screenshots/state returned by that same action call before
   choosing another action. Use the new observation ID; a separate observation call
   is needed only when the returned snapshot is insufficient or has become stale.

`get_window_state` options persist through automatic post-action refreshes.
`settle_ms` defaults to 200 (range 0–3000), is cancellable, and applies before each
snapshot. This delay allows ordinary UI updates but does not certify animation or
background loading completion (`render_complete_verified=false`). It is an AgentPark
policy, not a reproduced or verified Codex timing constant.

If refresh fails after input, the result reports `phase=post_action_observation`,
`input_dispatched=true`, `observation_available=false`, and the actual error.
Do not replay the input merely because the refresh failed. Reacquire/observe the
window to determine what happened. Failed input and refresh invalidate old IDs.

Window discovery includes untitled popups. Identities also include descriptive class,
owner, GUI thread, enabled, foreground, tool-window and non-activating-window fields;
these descriptive fields are refreshed, not used as process identity credentials.
Every observation reports native input-queue focus and `related_windows` from the
same process. `include_related=true` also captures at most three transient windows
with a native owner relation or tool windows in the same GUI thread. `screenshots`
contains up to four images, each with exact window identity, local bounds, a screenshot
ID and observation ID. `related_states` carries per-window focus/accessibility.
Use those per-window credentials for input; a main-window ID does not authorize a
popup click. Any input consumes the entire prior snapshot group. Clicking a popup
observed with its parent refreshes the original parent, including when the popup closes.
Uncaptured related windows remain discovery hints, not implicit input targets.
Omitted window IDs and per-popup observation errors are explicitly returned.

For a primary tool window unsupported by WGC, explicitly request
`capture_mode="visible_region"`. This captures the selected window's on-screen
rectangle, including anything covering it. It does not activate the window or
automatically replace a failed WGC capture. With `include_related=true`, related tool
windows use this visible-region mode by contract, without first attempting WGC.
Other related windows use the selected capture mode. Coordinate hit checks still reject
clicks covered by another window. Non-activating popups may receive pointer input
while their own GUI thread is foreground; keyboard input must still belong to the
selected window. Activation preserves the child focus of an already active window
and waits for native foreground activation to complete when switching windows.

`input_dispatched=true` and `result_verified=false` mean only that the input was
sent. Inspect the returned observation to verify the application result. A custom-drawn
application may expose only a root UIA window, which cannot identify its internal
search field versus canvas. Native focus detects HWND changes, not private widget
changes inside one HWND; visual verification remains necessary.

Example arguments (copy the actual window and IDs from tool results):

```json
{"window": {"id": 123, "app": "process:C:\\Example\\editor.exe", "pid": 456, "process_started": "copy actual timestamp"}, "include_text": true}
```

Window identity includes HWND, process executable, PID and process creation time.
Coordinates are relative to the returned window image; the backend adds its actual
screen origin, including negative coordinates on secondary monitors. Scroll uses
Windows wheel units: 120 is one notch; positive Y is down and positive X is right.

Observations expire after 60 seconds, belong to one Agent instance, and are consumed
by input attempts. Refreshing replaces the owner's previous snapshot group even when
the refresh fails. Window movement, process replacement, changed keyboard focus,
and controls that moved or disappeared require another observation. Coordinate
actions require a screenshot. UIA actions resolve runtime identities, not a fresh
enumeration with potentially changed indices. Screenshots use WGC with the exact
HWND for ordinary windows; capture errors are surfaced without automatically switching
capture modes. Image results are extracted into an ordered `images` tuple in the tool
execution protocol. All provider paths forward every image in order, and base64 payloads
are redacted from textual tool output; screenshot metadata identifies the images.

## Pointer feedback on action screenshots

After successful click/scroll/drag dispatch, the backend returns typed `PointerFeedback`
containing the exact screen coordinates passed to native input (including UIA-resolved
click points). The observation renderer draws X markers on a copy of each returned frame,
with local coordinate labels, cyan drag start and orange drag end. A two-axis 50 px ruler
has ticks exactly 10 native image pixels apart. PNG dimensions and input coordinates
are unchanged. This only annotates returned images; it does not draw over the live app.

`dispatched_pointer_points` retains the screen coordinates in the receipt, even if the
subsequent observation fails or screenshots were disabled. Each screenshot's
`action_overlay` reports local coordinates, visibility and ruler metadata. Mapping uses
the post-action frame origin, including negative desktop origins and parent refresh after
a popup closes. Out-of-frame points are reported without edge clamping; windows smaller
than 100 px on either axis omit the ruler explicitly. No overlays persist to an independent
`get_window_state` or non-pointer action. No pointer position is invented for keyboard
input or UIA semantic actions. Failed/partial input does not claim a completed annotation.

An X is a historical dispatched coordinate, not measured hit accuracy. Moving content,
scrolling and menus can change what lies under that coordinate. Compare targets in the
new frame; do not blindly compensate using an old layout. The skill teaches this distinction
and checking both drag endpoints. Image labels identify overlays as tool feedback.

## Configuration and runtime

Requires an interactive Windows desktop and the dependencies in `pyproject.toml`:
`pywinauto`, `windows-capture`, and their native dependencies. Install with
`python -m pip install -e .`. The backend imports lazily, allowing other AgentPark
features to run on other platforms. Computer Use itself reports unsupported there.

Computer Use can access all applications discoverable by the Windows backend.
Use `aumid:` IDs returned by `list_apps` to launch installed applications, or a
`process:` ID containing an existing absolute `.exe` path. Resulting windows use
`process:` IDs.

All AgentPark processes in a Windows session share a desktop input mutex and an
observation epoch. One input invalidates older observations in other processes.
This serializes AgentPark operations; it does not prevent a person or unrelated
automation program from using the desktop. Foreground, bounds, and hit-target
checks run during native input. Unicode input uses UTF-16 SendInput, including
Chinese and surrogate pairs. Keyboard and mouse buttons are released in cleanup.

These tools use cooperative cancellation. A configured tool deadline requests
cancellation and waits for cleanup before returning a timeout; it never detaches
native input. A Windows/UIA call blocked inside another application can delay that
return. WGC frame acquisition has an eight-second deadline; UIA traversal has
element, depth, text and time budgets, reported with `truncated` when reached.
Individual external COM calls cannot be forcibly interrupted by those budgets.
Password controls are excluded from text and semantic input operations. Elevated,
protected, minimized, or unavailable windows can require activation or reject access.

## Codex alignment boundary

The alignment is in the interaction contract: ordinary Agent tool orchestration,
explicit apps/windows, window observations, optional UIA text, screenshot/control
targeting, native Unicode input, and observable results for the next model step.
The implementation in `src/computer_use/` is independent. It does not embed Codex's
installed proprietary native backend, reproduce its Guardian service, or implement
its browser CUA REPL. `observation_id`, one-action invalidation, and wheel-unit scrolling
are explicit local contract differences.
The adopted interaction design is one action plus immediate observation in a single
model-facing call, bounded multi-image observations, and explicit recovery after failure.

## Validation

`python -m pytest tests/test_computer_use_service.py -q` checks stale observation
rejection, process identity, application discovery and launch, image forwarding,
cancellation, configured timeout cleanup and cross-service observation invalidation.

`python -X utf8 scripts/check_computer_use_windows.py` creates a disposable native
window and exercises actual WGC, UIA and SendInput through registered tools. It
closes only its own fixture window. This is opt-in because it moves focus/cursor.
It does not claim coverage of every external application or multiple-monitor DPI.
It also verifies automatic action refresh, a multi-image observation containing an
untitled non-activating popup, and clicking/closing that popup followed by parent refresh.
`tests/test_computer_use_observation_loop.py` covers these contracts with deterministic
scenes, including refresh errors, cancellation, image forwarding and capture bounds.
