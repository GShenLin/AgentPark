# Computer Use

Computer Use runs through the ordinary Agent tool loop. Enable `computer_use_tools`
in the node's Tools selection and choose a provider that supports tools and image
input. There is no separate GUI agent, nested model loop, or desktop pet process.
The folder context-menu entry opens the Companion CLI in the selected directory.

## Observe and act

1. `list_apps` / `list_windows`: discover applications and select an exact window.
2. `get_window` reacquires its identity; `activate_window` restores/focuses it.
3. `get_window_state`: inspect the PNG screenshot and, with `include_text=true`,
   UI Automation controls, focus, supported control values and selected text.
4. Call one of `click`, `drag`, `scroll`, `press_key`, `type_text`, `set_value`,
   or `perform_secondary_action`, passing the returned window and observation ID.
5. Observe again to verify the result before choosing another action.

Example arguments (copy the actual window and IDs from tool results):

```json
{"window": {"id": 123, "app": "process:C:\\Example\\editor.exe", "pid": 456, "process_started": "copy actual timestamp"}, "include_text": true}
```

Window identity includes HWND, process executable, PID and process creation time.
Coordinates are relative to the returned window image; the backend adds its actual
screen origin, including negative coordinates on secondary monitors. Scroll uses
Windows wheel units: 120 is one notch; positive Y is down and positive X is right.

Observations expire after 60 seconds, belong to one Agent instance, and are consumed
by input attempts. Refreshing replaces the owner's previous observation even when
the refresh fails. Window movement, process replacement, changed keyboard focus,
and controls that moved or disappeared require another observation. Coordinate
actions require a screenshot. UIA actions resolve runtime identities, not a fresh
enumeration with potentially changed indices. Screenshots use WGC with the exact
HWND; capture errors are surfaced without falling back to a full desktop image.

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

## Validation

`python -m pytest tests/test_computer_use_service.py -q` checks stale observation
rejection, process identity, application discovery and launch, image forwarding,
cancellation, configured timeout cleanup and cross-service observation invalidation.

`python -X utf8 scripts/check_computer_use_windows.py` creates a disposable native
window and exercises actual WGC, UIA and SendInput through registered tools. It
closes only its own fixture window. This is opt-in because it moves focus/cursor.
It does not claim coverage of every external application or multiple-monitor DPI.
