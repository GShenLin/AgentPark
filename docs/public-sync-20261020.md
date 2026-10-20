# Public feature synchronization - 2026-10-20

Source application changes after `025125ce` through
`54499512660fe85bb6641014a76792b21d7527a4` are applied to public `main`
after `8b0b05f22f1ed73c9b0163632691a66203ccf555`.
Private Git history is not imported.

## Included changes

- Independent user-interaction windows, typed interaction forms, request lifecycle
  handling, tool activation, and native clipboard support.
- Group leadership, group settings, prompt defaults, routing and task feedback.
- Knowledge library access, document reading, embedding/index updates and
  Companion MCP knowledge tools.
- Node event editor extraction, native harness model selection and preset fixes.
- Removal of the WorkBuddy provider, token bridge, local service manager,
  authorization UI, API routes, special protocol handling and associated tests/docs.
- Updated Chinese documentation; the English README no longer lists WorkBuddy.

## Public boundaries

Existing public history, configuration, deployment examples and public-only files
are preserved. Private provider configurations, account usage and personal agent
preset changes are excluded. Existing public README additions and test fixture
adjustments are retained by merging the source delta.

## Validation and limits

- WorkBuddy removal regression: 126 backend tests passed, including the HTTP
  transport boundary; frontend type check and production build passed.
- Desktop node-window contract, preload and window-host tests: 17 passed.
- Frontend: 393 tests passed in the local suite; the local obsolete harness-name
  test failed collection. The existing public version of that test was separately
  verified against the current source: all 21 tests passed.
- Expanded backend checks were not completed: the legacy Word conversion test
  failed in this execution environment and a skill-subprocess test did not finish
  promptly. These checks were interrupted; a complete backend pass is not claimed.
- Published tree checked against the intended file list; no unrelated private
  configuration changes are included.

This is source publication, not deployment or a full end-to-end acceptance run.
