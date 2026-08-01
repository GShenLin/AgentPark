# Curated Agent Profiles and RuntimePolicy A/B matrix

AgentPark keeps Agent Profiles as one file per Profile under `agent/*.json`. The curated
set adds task intent on top of a Provider: each task family has one dedicated
RuntimePolicy and two Profiles whose runtime fields are identical except for
`provider_id`. This makes the pair usable as an A/B comparison without silently changing
the policy, tools, prompts, Thinking mode, or reasoning effort.

## Matrix

| Task family | RuntimePolicy | Variant A | Variant B | Evidence level |
|---|---|---|---|---|
| Code reading | `code-reading` | `CodeReader_Kimi` | `CodeReader_Sonnet` | inferred |
| Architecture design | `architecture-design` | `ArchitectureDesigner_Official` | `ArchitectureDesigner_Krill` | experimental |
| Incident diagnosis | `incident-diagnosis` | `IncidentDiagnostician_Spark` | `IncidentDiagnostician_Doubao` | measured |
| Localized implementation | `localized-implementation` | `LocalizedImplementer_Official` | `LocalizedImplementer_Krill` | inferred |
| Cross-module implementation | `cross-module-implementation` | `CrossModuleImplementer_Official` | `CrossModuleImplementer_Krill` | inferred |
| Code review | `code-review` | `CodeReviewer_Sonnet` | `CodeReviewer_Official` | experimental |
| Test engineering | `test-engineering` | `TestEngineer_Official` | `TestEngineer_Kimi` | experimental |
| Refactoring planning | `refactoring-planning` | `RefactoringPlanner_Sonnet` | `RefactoringPlanner_Official` | experimental |
| Documentation maintenance | `documentation-maintenance` | `DocumentationMaintainer_Doubao` | `DocumentationMaintainer_Kimi` | inferred |
| Protocol integration | `protocol-integration` | `ProtocolIntegrator_Official` | `ProtocolIntegrator_Grok` | inferred |

`measured` means the exact task family has direct controlled benchmark evidence.
`inferred` means the Provider behavior was measured on a related task and the task fit is
an explicit inference. `experimental` means the pairing is a deliberate hypothesis that
still needs repeated A/B data. These labels prevent a curated choice from being presented
as stronger evidence than actually exists.

## RuntimePolicy intent

- `code-reading` is read-only and stops after it can explain the requested production
  path with file and symbol evidence.
- `architecture-design` is read-only and requires boundaries, contracts, alternatives,
  migration stages, failure behavior, verification, and rollback.
- `incident-diagnosis` is read-only and stops when one causal chain explains the primary
  failure and downstream symptoms.
- `localized-implementation` has a six-operation evidence checkpoint so a narrow change
  moves to a patch instead of indefinite exploration.
- `cross-module-implementation` keeps the task-direction ledger, consumer/risk closure,
  a twelve-operation checkpoint, and a completion review.
- `code-review` is read-only and reports only production-path-supported, actionable
  correctness or regression findings.
- `test-engineering` emphasizes public paths, deterministic oracles, failure semantics,
  and focused execution.
- `refactoring-planning` is read-only and produces behavior-preserving stages, stable
  seams, test gates, rollback points, and removal of superseded paths.
- `documentation-maintenance` verifies source truth, paths, commands, links, and relevant
  documentation gates before completion.
- `protocol-integration` treats authentication, requests, streaming, multi-turn state,
  tools, errors, and usage as one wire contract and distinguishes gateway failures from
  model behavior.

## Running an A/B comparison

1. Choose one task family and use the same repository revision, input, working path, and
   acceptance oracle for both Profiles.
2. Run variant A and variant B in fresh workspaces. Do not reuse message history or
   mutable artifacts between variants.
3. Require functional acceptance before comparing speed. A shorter failed run does not
   win.
4. Record completion, acceptance score, elapsed time, model turns, tool calls and
   failures, changed paths, input/output/reasoning/cache tokens, and Provider errors.
5. Repeat each variant at least three times. Compare completion rate first, then the
   median of passing runs; retain P95 when enough samples exist.

The A/B metadata is persisted in each Profile under `profile_metadata.ab_test`. The
selection UI shows the task family and A/B variant; hovering the variant badge shows the
experiment ID and paired Profile. The metadata contract is strict and is preserved when
the Node Profiler edits the operational Profile fields.

The benchmark runner records `profile_ab_comparison` for curated Profiles. Its
`controlled_configuration_sha256` covers node type, event rules, and every operational
field except `fields.provider_id`; identity and descriptive metadata are also outside the
hash. A valid pair must have the same controlled hash, the same experiment ID, opposite
variants, symmetric peer references, and different Provider IDs.
The suite runner validates those conditions before creating the result directory; a
mismatched curated Provider or a pair that changes another runtime field is rejected
before either variant runs.

## Evidence boundary

The initial Provider choices are based on the controlled 2026-08-01 comparison in
[模型同环境下的对比测试.md](模型同环境下的对比测试.md). The benchmark showed that a model
name alone is not a stable execution unit: identical models differed materially by
Provider, and a Grok path failed at the gateway protocol while another Provider using
the same model passed. The curated Profiles therefore name concrete Provider paths and
make evidence strength visible instead of claiming a provider-independent model rank.

The real implementation benchmark produced no fully passing result under the old
`coding-default` baseline. For that reason, implementation-oriented pairings are labeled
`inferred` rather than `measured`, and their dedicated policies explicitly target the
observed failure modes: excessive exploration, delayed patching, incomplete consumer
coverage, and build-only false confidence.
