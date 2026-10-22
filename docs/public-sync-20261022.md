# Public feature synchronization - 2026-10-22

Source application changes after `54499512660fe85bb6641014a76792b21d7527a4`
through `d4306fc0b69f02e0f516a321d645ba5a94e570d0` are applied to public
`main` after `0110024fac9cff72cf0ca9a3e50d707a0d64c069`.
Private Git history is not imported.

## Included changes

- Windows tray Working/Recent menus and NewNode action; node-window resize and persisted geometry.
- Tool reporting intervals preserve running tasks, with wait/status/cancellation controls.
- Editable tool prompts in settings with persistent overrides.
- Harness process lifecycle, process controls, provider tool protocols and permissions.
- Related computer-use, remote execution, tests and documentation updates.

## Public boundaries

Existing public-only files, README translations, configurations, deployment examples
and personal presets are preserved. Private agent/provider changes and local live-probe
validation records are excluded. Three files with previous public changes were merged:
remote workspace execution, remote registration tests, and provider refresh tests.
Remote execution retains worker-id payload cleanup alongside non-destructive reporting waits.

## Validation and limits

- Desktop node-window focused suite: 33 passed.
- Frontend focused suite: 8 files, 66 tests passed.
- HTTP transport boundary: 1 passed.
- Python syntax, conflict-marker, whitespace and credential-pattern checks completed.
- Published tree verified against the intended 232-file source delta; unrelated public blobs unchanged.
- Initial test attempts encountered sandbox temporary-directory permissions; focused reruns used a workspace temporary directory.
- Broader backend runs did not complete promptly and were interrupted; no complete backend pass is claimed.
- Desktop installer proxy integration was not validated successfully in this environment.

This is source publication, not deployment or full end-to-end acceptance.
