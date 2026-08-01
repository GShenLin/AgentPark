# RuntimePolicy and benchmark Harness

## Ownership

`RuntimePolicy` belongs to an Agent profile. Provider configuration owns transport
capabilities such as endpoint, authentication, model context capacity, and wire-level
tool-result limits. It no longer owns task-direction, completion-review,
implementation-checkpoint, or Agent context-compaction behavior. Provider compaction
fields remain the explicit contract only for raw, unbound provider runtimes.

An `agent_node` resolves policy in this order:

1. Read `fields.runtime_policy` from the node/Profile.
2. If it is absent, null, or an empty string, select the catalog default.
3. Load the versioned base policy from `config/runtimePolicies.json`.
4. Apply only the explicitly supplied, strictly validated section overrides.
5. Bind the immutable effective policy to the Agent runtime.

There is no implicit Provider fallback for Agent policy behavior.

## Profile configuration

The minimal explicit selection is:

```json
{
  "runtime_policy": {
    "policy_id": "coding-default"
  }
}
```

A Profile can override any first-version CodingRuntimePolicy parameter or prompt:

```json
{
  "runtime_policy": {
    "policy_id": "coding-default",
    "overrides": {
      "task_direction": {
        "enabled": true,
        "required_tools": [
          "get_task_direction",
          "replace_task_direction",
          "update_task_direction"
        ],
        "analysis_tools": [
          "run_analysis_verification",
          "finalize_analysis_report"
        ],
        "core_prompt": "A complete replacement core prompt.",
        "code_prompt": "A complete replacement coding prompt."
      },
      "completion_review": {
        "enabled": true,
        "passes": 2,
        "require_tool_executions": true,
        "require_done_criteria": true,
        "require_resolved_risks": true,
        "prompt": "A complete replacement completion-review prompt."
      },
      "implementation_checkpoint": {
        "enabled": true,
        "evidence_operation_limit": 12,
        "workspace_tool": "workspace_exec",
        "direct_evidence_tools": [
          "execute_console_command",
          "read_file",
          "rg_list_files",
          "rg_search_text"
        ],
        "workspace_evidence_kinds": [
          "list_files",
          "read_file",
          "run_command",
          "search_text"
        ],
        "patch_tools": ["apply_patch"],
        "workspace_patch_kinds": ["apply_patch"],
        "prompt": "A complete replacement implementation-checkpoint prompt."
      },
      "context_compaction": {
        "enabled": true,
        "every_tool_calls": 30,
        "input_tokens": 0,
        "current_input_tokens": 90000,
        "output_tokens": 0,
        "context_percent": 0,
        "max_candidate_chars": 50000,
        "gate_prompt": "A complete context-compaction checkpoint prompt.",
        "retry_prompt": "A complete context-compaction retry prompt."
      }
    }
  }
}
```

Unknown fields, wrong types, invalid ranges, duplicate tool names, missing policy ids,
and empty prompts fail before a Profile is saved or an Agent run starts.

The Settings page has a dedicated `RuntimePolicy` section. It can:

- switch the workspace default used by Profiles with no explicit selection;
- select any registered Policy and edit its validated source configuration;
- show which catalog entry is the current default.

Desktop and mobile Agent node configuration, together with the NodeProfiler
editor, expose the same catalog-backed base Policy selector. The
`runtime_policy` structured JSON field remains available for node/Profile-specific
overrides, and the effective preview shows:

- selected policy id and version;
- whether selection came from the default or Agent Profile;
- SHA-256 of the complete effective policy;
- source, character count, and SHA-256 of each injected prompt layer.

The same manifest is emitted with the first Responses request and captured by the
benchmark result.

## Policy catalog

The catalog lives at `config/runtimePolicies.json`. Each policy is a versioned JSON
file under `config/runtime_policies/`. Default prompt bodies are separate UTF-8 text
files so prompt changes are reviewable without editing Python source.

Adding a policy requires:

1. Add a complete policy JSON file.
2. Add its prompt files.
3. Register its id and relative path in the catalog.
4. Run `python -m pytest tests/test_runtime_policy.py -q`.

Catalog and prompt paths must stay inside `config/`; path traversal and absolute paths
are rejected.

The first catalog contains three explicit operating presets:

| Policy | Use when | Completion behavior |
|---|---|---|
| `coding-fast` | Localized implementation with a narrow owner and focused verifier | No review pass; short evidence budget |
| `coding-default` | Cross-module migrations, persistence, security, or ambiguous ownership | Direction ledger plus at most two reviews; unresolved criteria and risks block completion |
| `coding-diagnostic` | Read-only root-cause analysis | No patch checkpoint; stop immediately when supplied evidence closes the causal chain |

Preset choice is explicit Profile configuration. It does not alter model Thinking or
reasoning effort.

## Prompt injection path

Prompt files are not concatenated into a global system prompt at process startup.
They follow a typed, inspectable path:

1. The catalog loads the selected policy JSON and its UTF-8 prompt files.
2. Profile overrides replace only declared policy fields.
3. The resolver validates the complete effective policy and hashes it.
4. `agent_node` binds the immutable result to the Agent runtime context.
5. Task direction, completion review, implementation checkpoint, and context
   compaction read their own prompt field from that bound policy at the point where
   the behavior is invoked.
6. The first Responses request emits the effective manifest for audit and benchmark
   capture.

Editing a prompt file, selecting another policy, or supplying a Profile override is
therefore configurable and observable. No prompt body is hidden in Provider settings.

## Harness manifest

The suite runner accepts a strict JSON manifest:

```json
{
  "schema_version": 1,
  "suite_id": "coding-policy-v1",
  "repetitions": 3,
  "tasks": [
    {
      "id": "sample-task",
      "category": "backend-contract",
      "source_session_id": "optional-codex-session-id",
      "source_turn_id": "optional-source-turn-id",
      "prompt_file": "prompts/sample-task.md",
      "conversation_context_file": "contexts/sample-task.md",
      "oracle": {
        "source": "source-session",
        "reference": "source-turn-id",
        "acceptance_file": "acceptance/sample-task.md"
      },
      "fixture": {
        "repository": "D:/Project/source-repository",
        "revision": "immutable-git-revision",
        "submodules": false
      },
      "setup": [
        {
          "id": "dependencies",
          "argv": ["python", "-m", "pip", "--version"],
          "timeout_seconds": 30
        }
      ],
      "verification": [
        {
          "id": "focused-tests",
          "argv": ["python", "-m", "pytest", "tests/test_feature.py", "-q"],
          "timeout_seconds": 300,
          "required": true,
          "weight": 3
        }
      ],
      "output_checks": [
        {
          "id": "root-cause",
          "pattern": "authoritative transition",
          "required": false,
          "weight": 1
        }
      ],
      "required_changed_paths": ["src/**", "tests/**"],
      "forbidden_changed_paths": [".auth/**"],
      "benchmark_timeout_seconds": 3600
    }
  ],
  "runners": [
    {
      "id": "agent-coding-default",
      "node_type": "agent",
      "provider_id": "GPT_Official",
      "profile": "D:/Project/AgentPark/agent/GPT1.json"
    },
    {
      "id": "codex",
      "node_type": "codex",
      "provider_id": "GPT_Official"
    }
  ]
}
```

Run it with:

```powershell
python scripts/run_benchmark_suite.py `
  --manifest D:\benchmarks\suite.json `
  --output-dir D:\benchmarks\results\coding-policy-v1
```

Every case receives a fresh local Git clone at the exact requested revision. Setup,
prompt, verification, path gates, timeout, event journal, output, token usage, and
effective RuntimePolicy manifest are retained under the case directory.

For an Agent runner, `provider_id` in the runner is an explicit benchmark override of
the Profile's stored Provider. This makes one hashed Profile reusable across a Provider
matrix while every other Profile field and the effective RuntimePolicy remain fixed.
The selected Provider configuration is hashed separately in the runner contract.

Curated Profiles with `profile_metadata.ab_test` also emit a
`profile_ab_comparison` runner contract. Its controlled hash covers the node type,
event rules, and all operational Profile fields except `provider_id`; descriptive
metadata and Profile identity are outside that hash. An A/B pair is comparable only
when the controlled hashes and experiment IDs match, variants differ, peer references
are symmetric, and the selected Provider IDs differ.
The suite validates these conditions before creating its result directory and rejects a
curated Profile when the runner overrides it with a different Provider.

`conversation_context_file` is optional and is injected identically for all runners.
Use it only when the current request genuinely depends on earlier turns. The oracle is
mandatory, hashed into each run's input contract, and never shown to either runner.
Its source must be `source-session`, `user-specification`, or
`independent-specification`. This prevents a verifier from silently treating a later
implementation as the expected answer.

Each captured run contains four independent contracts:

- `input_contract`: hashes the prompt, optional conversation context, and hidden
  acceptance oracle;
- `fixture`: records both the requested revision and its resolved immutable Git commit;
- `runner_contract`: hashes the relevant Provider configuration, Profile, benchmark
  engine, reasoning settings, policy selection, and effective RuntimePolicy;
- `evaluation_contract`: records command arguments, weights, timeouts, output checks,
  path gates, external verifier hashes, and scoring-engine hashes.
- `workspace_state`: hashes the complete changed-path set and every changed file,
  deletion, and symlink target.

`--import-suite-result` accepts a frozen run only when all four contracts match.
Changing a verifier, policy prompt, Profile, Provider configuration, or mutable `HEAD`
invalidates reuse instead of silently preserving an old score.

To apply a revised verifier to an unchanged captured workspace, use the explicit
reverification path:

```powershell
python scripts/reverify_benchmark_suite.py `
  --manifest D:\benchmarks\suite.json `
  --source-suite-result D:\benchmarks\old\suite-result.json `
  --runner-id codex `
  --output-dir D:\benchmarks\reverified-codex
```

Reverification first checks the input, fixture, runner identity, and exact current
changed-path set. It then runs the current evaluator and emits a new evaluation
contract. It never changes or reruns the model output.

Legacy path-only workspace evidence is not upgraded implicitly. A one-time migration
requires `--upgrade-legacy-workspace-state`; the resulting execution provenance records
that content hashes were captured during reverification rather than during the
original model run. New runs capture content hashes at execution time.

## Ranking rule

Correctness is a gate, not a speed weight:

1. The benchmark process must complete.
2. Every required verification command must pass.
3. Every required output check must match.
4. Required and forbidden changed-path checks must pass.
5. Only runners with 100% verified completion across repetitions are eligible for a
   speed winner.
6. The eligible runner with the lowest median completed duration wins that task.

This prevents an incomplete run from appearing faster merely because it stopped early.
The report also retains mean completion score and median token count for diagnosis.

## Session sample set

`benchmarks/session_samples.json` records five provenance-backed Codex samples across:

- cross-module state transitions;
- runtime diagnosis;
- desktop/mobile UI;
- compiler configuration drift;
- configuration ownership migration.

The catalog includes completed, partial, and interrupted baselines. Before making a
sample runnable, capture the immutable pre-task Git revision and define independent
verification. Transcribe the acceptance oracle from the declared source before the
run. Do not reconstruct a fixture or expected behavior from the post-task workspace.

Current measured results and limitations are recorded in
`docs/runtime-policy-benchmark-results.md`.
