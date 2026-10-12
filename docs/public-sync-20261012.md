# Public feature synchronization - 2026-10-12

Source application changes from `ac0755122a33129b014fa24e3cf9e225f10aaa52`
through `cb460adabcb0457bc52ff8b95d73833968502f43` are applied to public
`main` after `38f29c6`. Existing public history, configuration examples and
public-specific source adjustments are preserved.

## Included changes

- Agent execution-device discovery, workspace inspection and switching, with
  the `cross-device-workflow` skill. Switching updates the current run's file
  and command workspace and model environment context. In-flight operations,
  terminal sessions and mixed switch/tool batches have explicit boundaries.
- Local Strata and ComfyUI service management in Settings, with manual service
  and model operations, owner access checks and the shared HTTP transport.
- Local Qwen Turbo single-image editing and node-memory skills.
- Turn-scoped skill activation, direct skill resource tools and deferred memory
  tool exposure, with explicit conversation-scoped activation when requested.
- Hermes stable-release discovery and validated PM installation generations;
  Codex model discovery using the latest official package version.
- Provider compaction defaults, theme defaults and composer interaction fixes.

## Public boundaries

Authentication aliases, provider credentials/configuration, account usage state
and machine-specific local-model registrations are excluded. Machine screenshots,
live device verification records and other `artifacts/` outputs are excluded.
The project-specific MetaHuman/BBQ animation snapshot skill and local Codex/Dot
repair snapshot skill are not part of this application-source publication.
Runtime data, private history, memories, dependencies and build output remain
outside the published changes.

Agent streaming tests now create their own temporary provider configuration.
This removes their dependency on the excluded local provider file, without
changing production behavior or weakening configuration validation.

## Validation

- Focused backend: 357 tests passed, 3 skipped, covering every changed backend
  test module and `tests/test_http_transport_boundary.py`. The skipped tests
  require an explicitly configured Hermes interpreter. Three dependency
  deprecation warnings remain.
- Frontend: 69 test files, 320 tests passed.
- Frontend type check and production build passed. Existing large-chunk
  warnings remain, including the Volcengine RTC dependency chunk.
- Publication path, credential-pattern, file-size and whitespace review.

This publication does not deploy a running service or upgrade connected devices.
The focused checks do not constitute a full backend regression run.
