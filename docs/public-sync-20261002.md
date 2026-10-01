# Public feature synchronization - 2026-10-02

Source application changes from `d558f652` through
`ea27010f3be7669ab9fc905ba3258279ebd6e61d` are applied to public `main`
after `ff19607`. Public history, README content, and public configuration
are preserved; private repository history is not imported.

## Included changes

- Remote endpoint registration with a runtime or an authentication coordinator,
  authenticated device discovery, remote execution, and cancellation.
- AgentPark runtimes publish their own execution capabilities; nodes can select
  another updated, admitted runtime without a standalone Remote process.
- Node remote device selection and disconnection, with remote directory browsing
  through the shared file tree in the initiating browser.
- Linux Remote build tooling and portable configuration paths.
- Codex node voice calls, multi-node conferences, and settings layout updates.

## Public boundaries

Provider configuration, account bindings, credentials, runtime data, attachments,
and built executables are excluded. Deployment defaults and examples use
`203.0.113.10`; configure your own coordinator address. Existing saved device
settings are not changed by this source synchronization.

Both AgentPark endpoints need the updated backend to publish runtime execution
capabilities. Updating the coordinator or browser assets alone is insufficient.

## Validation

- Focused backend: 64 tests passed, including remote execution, registration,
  directory browsing, peer networking, voice, and the HTTP transport boundary.
- Focused frontend: 6 test files, 26 tests passed.
- Frontend type check and production build passed (large chunk advisory remains).
- Publication path, credential-pattern, file-size, and whitespace checks passed.

This is a source publication, not a deployment to registered devices or a full
backend regression run. Windows and Linux binaries are not published as releases.
