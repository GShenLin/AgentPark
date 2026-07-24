from src.task_direction_context import CODE_TASK_PROTOCOL_CONTEXT


def test_code_task_protocol_bounds_verification_retries_and_requires_immediate_handoff():
    assert "allow one corrected" in CODE_TASK_PROTOCOL_CONTEXT
    assert "protocol rerun only" in CODE_TASK_PROTOCOL_CONTEXT
    assert "call replace_task_direction or update_task_direction" in CODE_TASK_PROTOCOL_CONTEXT
    assert "without a separate" in CODE_TASK_PROTOCOL_CONTEXT
    assert "full test run, build, or verification rerun" in CODE_TASK_PROTOCOL_CONTEXT
    assert "mutable defensive copy" in CODE_TASK_PROTOCOL_CONTEXT
    assert "tuple or mapping-proxy substitutes" in CODE_TASK_PROTOCOL_CONTEXT
    assert "construction contract separately from" in CODE_TASK_PROTOCOL_CONTEXT
    assert "must remain a constructor default" in CODE_TASK_PROTOCOL_CONTEXT
    assert "wire-key equality alone does not prove constructor compatibility" in CODE_TASK_PROTOCOL_CONTEXT
    assert "must raise the standard" in CODE_TASK_PROTOCOL_CONTEXT
    assert "dataclasses.FrozenInstanceError" in CODE_TASK_PROTOCOL_CONTEXT
    assert "without testing the public attribute itself" in CODE_TASK_PROTOCOL_CONTEXT
    assert "validate structural key presence and unknown keys before validating field" in CODE_TASK_PROTOCOL_CONTEXT
    assert "missing discriminator is a missing-required-field error" in CODE_TASK_PROTOCOL_CONTEXT
    assert "including removal of the discriminator" in CODE_TASK_PROTOCOL_CONTEXT
    assert "does not authorize narrowing" in CODE_TASK_PROTOCOL_CONTEXT
    assert "capture its baseline payload" in CODE_TASK_PROTOCOL_CONTEXT
    assert "complete HTTP/RPC handler" in CODE_TASK_PROTOCOL_CONTEXT
    assert "internal broker/domain fragment is not the external response baseline" in CODE_TASK_PROTOCOL_CONTEXT
    assert (
        "FLOW, FINAL_BOUNDARY, REQUEST_OWNER, RESPONSE_OWNER, REQUEST_KEYS, RESPONSE_KEYS,"
        in CODE_TASK_PROTOCOL_CONTEXT
    )
    assert "do not reread already traced files" in CODE_TASK_PROTOCOL_CONTEXT
    assert "exactly two implementation stages" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Do not combine both stages into one giant" in CODE_TASK_PROTOCOL_CONTEXT
    assert "patch, postpone Stage 1 tests" in CODE_TASK_PROTOCOL_CONTEXT
    assert "whole-file reads between the" in CODE_TASK_PROTOCOL_CONTEXT
    assert "stored boundary trace and the Stage 1 patch" in CODE_TASK_PROTOCOL_CONTEXT
    assert "persist that trace and apply\nStage 1 in one ordered workspace_exec call" in CODE_TASK_PROTOCOL_CONTEXT
    assert "standalone model round on the trace update" in CODE_TASK_PROTOCOL_CONTEXT
    assert "run the planned focused checks before rereading changed files" in CODE_TASK_PROTOCOL_CONTEXT
    assert "progress_timeout_seconds" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Do not enable this watchdog for the repository-wide" in CODE_TASK_PROTOCOL_CONTEXT
    assert "do not call update_task_direction merely to restate" in CODE_TASK_PROTOCOL_CONTEXT
    assert "call\nrun_analysis_verification directly" in CODE_TASK_PROTOCOL_CONTEXT
    assert "records a newly discovered risk that affects the next action" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Initialize it exactly once with replace_task_direction" in CODE_TASK_PROTOCOL_CONTEXT
    assert "send only changed hypotheses" in CODE_TASK_PROTOCOL_CONTEXT
    assert "one or two independent operations" in CODE_TASK_PROTOCOL_CONTEXT
    assert "three or more independent\nworkspace reads, searches, inventories, or commands" in CODE_TASK_PROTOCOL_CONTEXT
    assert "one concurrent\nnon-mutating workspace_exec stage" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Do not replace one\nbatch with many direct read_file calls" in CODE_TASK_PROTOCOL_CONTEXT
    assert "native-command operands and search roots" in CODE_TASK_PROTOCOL_CONTEXT
    assert "mixed list of\npossibly absent files or directories" in CODE_TASK_PROTOCOL_CONTEXT
    assert "structured list_files discovery first" in CODE_TASK_PROTOCOL_CONTEXT
    assert "git status in a separate operation from optional discovery" in CODE_TASK_PROTOCOL_CONTEXT
    assert "exit code 2 from a missing/search-error target remains a real failure" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Stage 1-to-Stage 2 handoff in one workspace_exec call" in CODE_TASK_PROTOCOL_CONTEXT
    assert "exclusive first stage calls update_task_direction" in CODE_TASK_PROTOCOL_CONTEXT
    assert "exclusive\nsecond stage calls apply_patch" in CODE_TASK_PROTOCOL_CONTEXT
    assert "ordered and\nfail-fast" in CODE_TASK_PROTOCOL_CONTEXT
    assert "standalone Stage 1 update and a later round" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Every Agent-side apply_patch operation, direct or inside workspace_exec, must include non-empty" in CODE_TASK_PROTOCOL_CONTEXT
    assert "do not submit an unrelated easy requirement" in CODE_TASK_PROTOCOL_CONTEXT
    assert "inventory every executable reference" in CODE_TASK_PROTOCOL_CONTEXT
    assert "included as its own Stage 2 replacement requirement" in CODE_TASK_PROTOCOL_CONTEXT
    assert "import replacement alone does not prove" in CODE_TASK_PROTOCOL_CONTEXT
    assert "file-size policy to the projected final source" in CODE_TASK_PROTOCOL_CONTEXT
    assert "later patch/test rounds on line-count or blank-line cleanup" in CODE_TASK_PROTOCOL_CONTEXT
    assert "final route registry/decorator binding" in CODE_TASK_PROTOCOL_CONTEXT
    assert "callable signature, parameter annotations, dependency injection" in CODE_TASK_PROTOCOL_CONTEXT
    assert "parse raw dict/object input inside the boundary" in CODE_TASK_PROTOCOL_CONTEXT
    assert "validation matrix for every canonical envelope key" in CODE_TASK_PROTOCOL_CONTEXT
    assert "including identifiers such as\ntask_id" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Make the matrix lifecycle-aware" in CODE_TASK_PROTOCOL_CONTEXT
    assert "bootstrap registration request may intentionally accept an empty token" in CODE_TASK_PROTOCOL_CONTEXT
    assert "issued\nregistration response or established-session credential requires a non-empty token" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Stage 1 direct contract tests own the exhaustive missing, unknown" in CODE_TASK_PROTOCOL_CONTEXT
    assert "one representative invalid payload per\ndistinct boundary" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Do not duplicate the full canonical\nfield matrix" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Do not run throwaway shell or REPL probes" in CODE_TASK_PROTOCOL_CONTEXT
    assert "let the focused pytest command provide the evidence" in CODE_TASK_PROTOCOL_CONTEXT
    assert "do not open a new framework-signature inventory" in CODE_TASK_PROTOCOL_CONTEXT
    assert "map every pre-existing focused test assertion" in CODE_TASK_PROTOCOL_CONTEXT
    assert "stale\nowner-specific error label assertion" in CODE_TASK_PROTOCOL_CONTEXT
    assert "pytest.raises match strings or equivalent exact error-text assertions" in CODE_TASK_PROTOCOL_CONTEXT
    assert "old-owner label and canonical-owner label explicitly" in CODE_TASK_PROTOCOL_CONTEXT
    assert "changing the call from a legacy wrapper to from_payload is not sufficient" in CODE_TASK_PROTOCOL_CONTEXT
    assert "appears both in a patch deletion line and" in CODE_TASK_PROTOCOL_CONTEXT
    assert "required_changes.new_text" in CODE_TASK_PROTOCOL_CONTEXT
    assert "top-level test function or class as an indivisible patch region" in CODE_TASK_PROTOCOL_CONTEXT
    assert "never between statements belonging to an" in CODE_TASK_PROTOCOL_CONTEXT
    assert "contains only evidence not already stored" in CODE_TASK_PROTOCOL_CONTEXT
    assert "Run those expensive commands exactly once inside their final gates" in CODE_TASK_PROTOCOL_CONTEXT
    assert "never a focused file subset" in CODE_TASK_PROTOCOL_CONTEXT
