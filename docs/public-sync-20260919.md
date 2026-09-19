# Public feature synchronization — 2026-09-19

This change brings the public repository's application code forward from the
source snapshot `b7d29f9` to `ed5719c1`. The public base is
`320d3a5dcbd6322ee3e8aa63f311fa7585502197` on `main`.
The repositories have unrelated commit histories, but the base snapshot's
`src`, `nodes`, `functions`, and `webui` trees are identical to the public base.
Only subsequent feature changes and their dependencies are included.

## Included capabilities

- Harness installation, updates, model binding, native sessions, and runtime
  event projection, including Hermes, Pi, OpenClaw, and DeepSeek Harness.
- Knowledge libraries with retrieval, Office document ingestion, table queries,
  configuration UI, and the knowledge skill.
- Conversation context compaction and node long-term memory, with the associated
  replacement of legacy operational-memory paths.
- Peer networking, browser portal, device enrollment, TURN support, and mobile
  workspace reconnection and navigation.
- Provider and gateway improvements, image generation support, usage reporting,
  model selection, and related UI fixes.
- Startup recovery, server restart handling, host-shell support, computer-use
  updates, and the Archify diagram skill.

Wyckoff integration and a configurable ACP agent registry are not implemented
by this synchronization.

## Public repository boundaries

The existing public README files and intentional public-only omissions remain.
Local provider credentials and bindings, authentication state, node histories,
generated certificates, runtime installations, caches, logs, research output,
personal instructions, and local marketing-skill installations are excluded.
The private Git history is not merged or pushed.

Deployment-specific addresses in the new peer-network feature use the reserved
documentation address `203.0.113.10`. It is not a working public service. Configure
your own coordinator address and deployment certificate constraints before use.
Generate and distribute your own trust certificates; none are bundled.
Memory settings use an empty provider selection so they inherit the configured
node provider instead of referring to a developer's private provider ID.

## Validation

- Frontend: 40 test files, 180 tests passed.
- Frontend production build: passed, with the existing large-chunk advisory.
- Changed backend test modules: 1,033 passed, 27 skipped, 7 failed.
- All seven failures reproduce in the original source checkout:
  - Three real Codex smoke cases fail because the installed runtime emits a
    namespace tool containing children unsupported by the current gateway
    conversion (`namespace tool 'functions' supports only function children`).
  - Four tests depend on stale local provider assumptions: absent
    `deepseek_v4_pro` / `deepseek_v4_flash` entries or a Tavern model field that
    has changed from a scalar to a list.
- The backend run used a disposable, credential-free local provider fixture for
  configuration-dependent image tests. This fixture is ignored and not committed.
- An initial full-suite attempt stopped on missing private provider configuration;
  no full-suite success is claimed. Skipped native tests require their documented
  external runtimes or opt-in environment variables.
- Staged patch whitespace check passed. Staged paths exclude credentials,
  generated trust material, and runtime state.

This synchronization is submitted as a draft pending resolution of the known
Codex compatibility and configuration-dependent test issues.
