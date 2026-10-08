# Public feature synchronization - 2026-10-08

Source application changes from `ea27010f3be7669ab9fc905ba3258279ebd6e61d`
through `ac0755122a33129b014fa24e3cf9e225f10aaa52` are applied to public
`main` after `5c89860`. Public history, README content, and public configuration
are preserved; private repository history is not imported.

## Included changes

- Shared voice provider contracts for OpenAI realtime, Doubao speech, and
  Volcengine RTC, with node-owned settings, screen sharing, durable call records,
  task progress delivery, and desktop/mobile call presentation.
- Node cron tools, persisted schedules, execution, and lifecycle handling.
- WeChat article parsing and the bundled article-reading skill.
- Incremental Board ICE signaling, remote connection improvements, and the
  updated MCP transport behavior for remote hosts.
- Related dependencies, UI, and regression tests.

## Public boundaries

Local authentication aliases, provider credentials and bindings, provider probe
results, public gateway account configuration, and Companion memory settings
are excluded. Runtime data, attachments, generated certificates, dependencies,
and build output are not published. Existing public deployment examples remain.

Two schema tests now use temporary audio catalog paths so they can run without
private provider configuration. Production behavior is unchanged by this test
isolation adjustment.

## Validation

- Focused backend: 264 tests passed, covering every changed backend test module
  and the HTTP transport boundary. One Starlette test-client deprecation warning.
- Frontend: 69 test files, 320 tests passed.
- Frontend type check and production build passed; large-chunk warnings remain,
  including the Volcengine RTC dependency chunk.
- Publication path, credential-pattern, file-size, and staged whitespace checks.

This is a source publication. It is not a full backend regression run, a running
service deployment, or real provider/device acceptance testing.
