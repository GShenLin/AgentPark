from __future__ import annotations

import json

from src.task_direction_store import TaskDirectionStore


TASK_DIRECTION_CONTEXT_PREFIX = '<agentpark_task_direction schema_version="2">'
TASK_DIRECTION_CONTEXT_SUFFIX = "</agentpark_task_direction>"
CODE_TASK_PROTOCOL_CONTEXT = """<agentpark_code_task_protocol schema_version="1">
For non-trivial repository work, maintain an explicit task direction state with get_task_direction,
replace_task_direction, and update_task_direction. Initialize it exactly once with replace_task_direction;
for intermediate progress use update_task_direction to append evidence and send only changed hypotheses,
risks, or criteria. Never resend unchanged ledger items through replace_task_direction.
The state is the authoritative working ledger for the objective, architecture hypotheses, evidence,
unresolved risks, and done criteria. Initialize it before broad exploration, update it when evidence
changes a hypothesis or criterion, and never mark a criterion met without evidence ids.
Task direction is scoped to the current task_id. Never attempt to recover or reuse direction state from
another task directory.

Use direct parallel function calls for one or two independent operations. When three or more independent
workspace reads, searches, inventories, or commands are already known, place them in one concurrent
non-mutating workspace_exec stage so results stay attributable without multiplying top-level tool calls.
Use additional workspace_exec stages only when later operations depend on earlier results. Do not replace one
batch with many direct read_file calls, and do not use a model-visible parallel wrapper.
Discover optional files before placing strict read_file operations in a workspace_exec stage. A missing
optional path is a real operation failure; only batch reads whose paths are known to exist or whose failure
should invalidate that stage.
This discovery rule also applies to native-command operands and search roots. Do not pass a mixed list of
possibly absent files or directories to Get-ChildItem, rg, git, or another command and let one missing operand
poison otherwise valid inventory results. Use structured list_files discovery first, then read or search only
returned paths. Keep required diagnostics such as git status in a separate operation from optional discovery
because their failure semantics differ. For rg, an explicitly checked exit code 1 may represent a known
no-match branch; exit code 2 from a missing/search-error target remains a real failure and must not be masked.

Before implementation, define the focused verification command for each high-risk done criterion and select
the repository's full test/build commands. For public contracts, cover accepted and rejected values, exact
observable shapes, ownership/aliasing, and mutability separately. In particular, distinguish immutable
internal storage from a mutable defensive copy returned to a caller. An immutable contract object forbids
attribute rebinding; it does not justify exposing tuple or mapping-proxy substitutes when the public value
is specified as a defensive copy. Every collection-valued public accessor and to_payload result must be
tested by mutating the original input and every separately returned value, then verifying internal state,
the other returned values, and later serialization are unchanged.
Before replacing or introducing a public contract class, preserve its construction contract separately from
its wire parser: positional/keyword call shape, field order, defaults, constant discriminator fields, and
public property behavior when a discriminated value is absent. A constant success/version field in a
constructible response object must remain a constructor default rather than forcing every caller to restate
the invariant. Direct tests must instantiate the object through the minimal valid public call as well as
through from_payload; wire-key equality alone does not prove constructor compatibility. If immutability is
implemented with a frozen dataclass, direct assignment to every public field/property must raise the standard
dataclasses.FrozenInstanceError. Do not assume that frozen private backing fields, generated slots, and public
properties preserve the same assignment exception without testing the public attribute itself.
For every strict object contract, validate structural key presence and unknown keys before validating field
values. For a discriminated union, a missing discriminator is a missing-required-field error; only a present
discriminator is type-checked and then used to select the exact branch shape. Table-driven tests that remove
each required key must observe the same missing-required category, including removal of the discriminator.

A canonical-contract migration does not authorize narrowing an existing public or transport boundary from
raw payloads to pre-parsed objects. Inventory each named boundary's existing callable shape and direct
callers. Keep strict parsing at every boundary that accepts external data, and directly test invalid raw
input against that boundary before asserting that state or execution remains unchanged.
For each cross-layer wire flow, preserve one compact source evidence item before implementation using this
exact field order: FLOW, FINAL_BOUNDARY, REQUEST_OWNER, RESPONSE_OWNER, REQUEST_KEYS, RESPONSE_KEYS,
INTERNAL_DRAFT, SOURCE_PATHS. Trace each field from the externally callable route through domain code to the
serializer; do not infer the final envelope from an internal return fragment. Once this evidence is in the
ledger, do not reread already traced files unless a focused failure identifies a specific locus.
Once the boundary trace is complete and the Stage 1 patch is fully planned, persist that trace and apply
Stage 1 in one ordered workspace_exec call: an exclusive update_task_direction stage followed by an
exclusive apply_patch stage, with context_checkpoint="retain_until_next_handoff". Stage 1 is an intermediate
implementation boundary: its successful focused test must not retire the Stage 1 mutation before Stage 2
is constructed. Do not spend a standalone model round on the trace update when no unresolved
evidence is needed to construct the already-planned Stage 1 patch. The ordered program remains fail-fast,
so Stage 1 must not mutate files if trace persistence fails.
Execute a cross-layer canonical-contract migration in exactly two implementation stages. Stage 1 adds the
canonical contract module and its direct contract tests, then runs only that planned focused pytest command
with the semantic watchdog. Stage 2 migrates the named boundaries and adds their integration tests, then runs
the planned boundary-focused pytest command with the watchdog. Do not combine both stages into one giant
patch, postpone Stage 1 tests until after migration, or insert new inventory/whole-file reads between the
stored boundary trace and the Stage 1 patch. A Stage 1 failure may reopen only its failing contract locus; a
Stage 2 failure may reopen only its failing boundary locus.
Before emitting the Stage 1 patch, apply the repository's file-size policy to the projected final source:
choose the final responsibility split and compact layout up front. Do not knowingly create an oversized
implementation, run passing tests, and then spend later patch/test rounds on line-count or blank-line cleanup.
The first Stage 1 patch must already represent the intended policy-compliant module layout.
Do not run throwaway shell or REPL probes for standard language/library semantics that the planned Stage 1
contract tests already cover, such as frozen-dataclass assignment or defensive-copy behavior. Encode the
observable requirement in the direct tests and let the focused pytest command provide the evidence. A separate
probe is justified only for an environment-specific unknown that changes the implementation design and is not
covered by a preselected focused test.
After Stage 1 focused tests pass, perform the Stage 1-to-Stage 2 handoff in one workspace_exec call:
an exclusive first stage calls update_task_direction with the Stage 1 evidence delta, and an exclusive
second stage calls apply_patch with the complete Stage 2 migration, with
context_checkpoint="retire_after_verified". Stage 2 is the terminal implementation boundary, so its
successful structured pytest completion may retire the Stage 2 mutation before final verification. The workspace program is ordered and
fail-fast, so the patch is not attempted if direction persistence fails. Do not spend one model round on a
standalone Stage 1 update and a later round on the already-planned Stage 2 patch.
Every Agent-side apply_patch operation, direct or inside workspace_exec, must include non-empty
required_changes. Use addition entries for the
critical new Stage 1 contract/test symbols. For Stage 2, every exact old-owner/new-owner or other textual
replacement recorded in the boundary ledger must appear as a replacement entry, alongside additions for the
critical migrated boundaries. The runtime verifies those entries against patch removal/addition lines before
mutation; do not submit an unrelated easy requirement while omitting a recorded patch obligation.
Before removing a legacy import, alias, or local name binding, inventory every executable reference to that
binding in the named migration consumers. Either preserve the binding deliberately, or replace every reference
that would otherwise become undefined. Each required call-site change must be recorded in the boundary trace
and included as its own Stage 2 replacement requirement; import replacement alone does not prove that runtime
consumers were migrated.
Before emitting the Stage 2 patch, map every pre-existing focused test assertion to the validation owner
after migration. If an exact alias necessarily moves validation to the canonical owner, update any stale
owner-specific error label assertion in the same Stage 2 patch; otherwise preserve the existing assertion.
Do not knowingly launch the focused suite with stale assertions that the planned ownership change invalidates.
For each legacy parser or validator replaced by an exact canonical alias, search its focused tests for
pytest.raises match strings or equivalent exact error-text assertions during the boundary trace. Record the
old-owner label and canonical-owner label explicitly, and include every required assertion update in the
Stage 2 patch; changing the call from a legacy wrapper to from_payload is not sufficient by itself.
Before the Stage 2 tool call, ensure each recorded old-owner literal appears both in a patch deletion line and
as required_changes.old_text, and each canonical-owner literal appears both in an addition line and as
required_changes.new_text.
For an HTTP/RPC framework boundary, the stored trace must include the final route registry/decorator binding,
the callable signature, parameter annotations, dependency injection, and the raw payload type the framework
passes. Preserve that externally registered callable contract; parse raw dict/object input inside the boundary
instead of replacing a framework-facing annotation with a canonical internal class. Before the Stage 2 patch,
build one accepted/rejected validation matrix for every canonical envelope key, including identifiers such as
task_id, and include the required boundary tests in that same patch. Make the matrix lifecycle-aware: when a
field changes admissibility by phase or direction, record each phase separately instead of applying a blanket
rule. For example, a bootstrap registration request may intentionally accept an empty token while an issued
registration response or established-session credential requires a non-empty token. After the Stage 2 focused
suite passes, run only the preselected narrow static checks; do not open a new framework-signature inventory
unless a specific failing check identifies that locus.
Keep validation-test ownership explicit. Stage 1 direct contract tests own the exhaustive missing, unknown,
type, numeric, discriminator, and mutation-isolation matrix. Stage 2 boundary tests must prove that each raw
boundary invokes canonical parsing before mutation or execution, using one representative invalid payload per
distinct boundary plus the required exact success/failure end-to-end flows. Do not duplicate the full canonical
field matrix in every broker, API, worker-client, or operation-registry integration suite.
Treat every existing top-level test function or class as an indivisible patch region. Insert a new top-level
test only at a verified top-level def/class boundary or end of file, never between statements belonging to an
existing test. Include enough unchanged structural context in the patch hunk to prove the insertion boundary.
Before replacing any successful wire serializer, capture its baseline payload and assert exact key/value
equality after migration, including constant discriminator or success fields such as "ok". Matching only
the typed data fields is not wire compatibility. Trace the value through the complete HTTP/RPC handler to
the final network response; an internal broker/domain fragment is not the external response baseline. A
canonical response contract must own the complete external envelope, including wrapper fields previously
added by a route, and the route must return that canonical serialization rather than rebuilding the wrapper.

Add the focused contract tests before or in the same patch as the implementation. After a successful patch,
run the planned focused checks before rereading changed files. Inspect only a failing locus or a narrow diff;
do not repeatedly dump whole modified files or repeat repository inventories already preserved by the task
direction ledger or compaction checkpoint.
For focused pytest commands launched with execute_console_command, select an explicit
progress_timeout_seconds before implementation and use the pytest semantic watchdog. It counts completed-test
markers on stdout, not logging or repeated tracebacks. Do not enable this watchdog for the repository-wide
full_test gate; that gate retains its explicit overall timeout.

For codebase analysis, run the analysis verification protocol before the final answer. The protocol must
cover security, the full test suite, builds, configuration drift, and worktree state. A failing gate is valid
evidence and must be reported; it must not be hidden or converted to a pass.
After the last focused check, do not call update_task_direction merely to restate accumulated evidence or
pre-mark criteria immediately before run_analysis_verification. Keep those final criteria pending and call
run_analysis_verification directly; finalize_analysis_report atomically records the verification evidence and
resolves them. An intermediate direction update remains valid only when it changes the planned implementation,
records a newly discovered risk that affects the next action, or is needed before more implementation work.
Use focused checks to validate candidate commands before the protocol run. Do not rerun the full protocol
merely because a gate found a defect. If a protocol command itself did not execute, allow one corrected
protocol rerun only. After the final protocol run, do not perform another source/config inventory and do not
call replace_task_direction or update_task_direction. Pass a compact direction_completion directly to finalize_analysis_report; it
must add the final evidence and resolve every pending done criterion against the current revision.
direction_completion.evidence contains only evidence not already stored in the ledger, with fresh ids; use
an empty array when all final evidence is already stored, and reference existing evidence ids only from
hypothesis, risk, and criterion resolutions.
Do not execute the repository's full test command or complete release/package build as a candidate check
before run_analysis_verification. Run those expensive commands exactly once inside their final gates. The
full_test gate must use the preselected repository-wide command, never a focused file subset; focused tests
belong only in pre-verification checks or the security gate when they validate security boundaries.

Final analysis output is layered through finalize_analysis_report: the main answer contains conclusion,
decisive evidence, and prioritized actions. Exhaustive inventories belong in the appendix artifact. Do not
repeat raw file catalogs in the main answer. finalize_analysis_report atomically completes the task direction
ledger with the supplied direction_completion. Call it immediately after verification without a separate
get_task_direction, source inventory, full test run, build, or verification rerun.
</agentpark_code_task_protocol>"""


def inject_task_direction_context(agent: object, *, role: str) -> None:
    function_map = getattr(getattr(agent, "tools", None), "function_map", None)
    required_tools = {
        "get_task_direction",
        "replace_task_direction",
        "update_task_direction",
    }
    if not isinstance(function_map, dict) or not required_tools.issubset(function_map):
        return
    agent.Message(role, CODE_TASK_PROTOCOL_CONTEXT, persist=False)
    stored = TaskDirectionStore.for_agent(agent).read()
    if stored is None:
        return
    payload = stored.to_payload()
    context = (
        TASK_DIRECTION_CONTEXT_PREFIX
        + "\n"
        + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        + "\n"
        + TASK_DIRECTION_CONTEXT_SUFFIX
    )
    agent.Message(role, context, persist=False)
