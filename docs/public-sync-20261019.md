# Public feature synchronization - 2026-10-19

Source application changes from `cb460adabcb0457bc52ff8b95d73833968502f43`
through `025125ce` are applied to public `main` after `a556989`.
Public history and configuration are preserved; private Git history is not imported.

## Included changes

- Updated Chinese project overview, getting-started guide, documentation index,
  and Settings manuals covering models, connectivity, defaults, diagnostics,
  knowledge, local services, presets, skills, events, themes and gateways.
  The English landing page links to the new guides and summarizes recent changes.
- Windows node windows, native dragging/minimize/restore, persisted-result alerts,
  unread state, clipboard attachments and Electron installer proxy handling.
- Toolset management, Companion preset selection, node preset naming and layout,
  graph creation, and light-theme presentation updates.
- OpenCode and Antigravity harnesses, WorkBuddy integration, and custom local
  service adapters with explicit lifecycle contracts.
- Voice screenshots, screen annotations, shared conversation context, draft
  editing, task delivery, provider error isolation and reconnection behavior.
- Curl stream diagnostics, Responses tool/stream recovery, peer cleanup, startup
  recovery, and frontend deployment tooling.
- Browser automation and UI asset exploration skills.

## Public boundaries

Local model-provider bindings, account usage, private configuration and personal
agent preset changes are excluded. The project-specific Unreal video mocap skill,
its snapshot test, and live voice acceptance artifacts are also excluded.
Runtime files, memories, attachments, dependencies and build output are not published.
Deployment examples use the reserved `203.0.113.10` address and a placeholder
Workbench instance ID; users must configure their own deployment.

The existing public Curl payload-cleanup contract is retained with the incoming
stream diagnostic implementation. Public regression tests use temporary provider
fixtures and current component/export names instead of private provider files or
obsolete UI locations. These test updates do not alter production behavior.

## Validation

- Focused backend: 546 tests passed across 44 modules, including the HTTP transport
  boundary. One Starlette test-client deprecation warning remains.
- Frontend: 84 test files, 401 tests passed.
- Desktop window, installer networking and annotation tests: 22 passed.
- Frontend type check and production build passed. Existing large-chunk warnings
  remain, including the Volcengine RTC dependency chunk.
- Publication path, credential-pattern, file-size and staged whitespace review.

This is a source publication, not deployment of a running service or connected
devices. The focused backend checks are not a full regression run; provider calls
and native window interaction were not independently exercised in this sync.
