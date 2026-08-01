# RuntimePolicy benchmark results

For the controlled same-Profile, same-RuntimePolicy Provider/model matrix run on
2026-08-01, see [模型同环境下的对比测试.md](模型同环境下的对比测试.md).
The task-specific Profile/RuntimePolicy pairs derived from those observations are
documented in [curated-agent-profiles.md](curated-agent-profiles.md).

## Scope and controls

These are controlled single-repetition measurements, not a claim of universal model
superiority. Both runners used high reasoning effort. The Agent Profile also retained
`thinking: enabled`; no result was produced by lowering or disabling Thinking.

Every reported winner passed the same hidden acceptance oracle, immutable fixture,
required verification commands, output checks, and changed-path gates. Frozen results
were reused only through matching input, fixture, runner, and evaluation contracts.

## Current validated results

| Task category | Agent policy | Agent | Codex | Relative result |
|---|---|---:|---:|---|
| Desktop/mobile UI | `coding-fast` | 175.1 s / 522,448 tokens | 416.8 s / 2,835,415 tokens | 2.38× faster; 81.6% fewer tokens |
| Configuration ownership migration | `coding-default` | 856.5 s / 1,653,611 tokens | 1,138.4 s / 7,051,015 tokens | 1.33× faster; 76.5% fewer tokens |
| Runtime-evidence diagnosis | `coding-diagnostic` | 15.4 s / 9,674 tokens | 20.0 s / 16,679 tokens | 1.29× faster; 42.0% fewer tokens |

All six compared runs reached 100% verified completion.

Authoritative result files:

- `D:\Project\benchmark-results\coding-policy-fast-ui-v3-r1-final-v2\suite-result.json`
- `D:\Project\benchmark-results\coding-policy-quality-cache-r2-final-v2\suite-result.json`
- `D:\Project\benchmark-results\coding-policy-diagnostic-v2-r1-final-v2\suite-result.json`

These historical workspaces were upgraded once from path-only evidence to changed-file
content hashes during explicit reverification; that fact is recorded in each run's
execution provenance. Future runs capture those hashes at execution time.

## What changed performance

The first quality policy lost the UI sample: its implementation was already correct,
but a mandatory completion-review pass added roughly 144 seconds and prompted an
optional extra test. The fast preset removes that review for narrowly scoped tasks and
uses a six-operation evidence checkpoint.

The first diagnostic preset also lost: it spent 69.4 seconds and 92,065 tokens
re-reading code even though the supplied incident evidence already formed a complete
causal chain. Version 1.1 makes evidence sufficiency explicit and reduced the same
Agent task to 15.4 seconds and 9,674 tokens.

The configuration migration exposed the opposite risk. Fast variants stopped before
the Settings UI was migrated. The quality preset's direction ledger and deterministic
done-criteria/risk gate kept the cross-module acceptance boundary active until the UI,
backend rejection, path owner, focused tests, and build were all covered.

The practical strategy is therefore routing, not one universal prompt:

- use `coding-fast` only when ownership and verification are narrow;
- use `coding-default` when missing one consumer would make the task incomplete;
- use `coding-diagnostic` when the requested outcome is explanation rather than a
  patch.

## Remaining evidence gap

One repetition per task is enough to validate the mechanism and detect large
differences, but not to estimate variance. Before treating these ratios as stable,
run at least three repetitions on each task and add compiler/configuration-drift and
cross-module state-transition fixtures. Medians and 100% completion across all
repetitions remain the promotion gate.
