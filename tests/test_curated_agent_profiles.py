import json
import shutil
from pathlib import Path

import pytest

from scripts.benchmark_harness_contract import RunnerSpec
from scripts.benchmark_harness_evidence import (
    runner_execution_contract,
    validate_profile_ab_runner_contracts,
)
from src.runtime_policy import RuntimePolicyCatalog
from src.web_backend.profile_metadata import (
    profile_ab_comparison_contract,
    validate_profile_metadata,
)
from src.web_backend.profile_storage import read_profile_file


PROJECT_ROOT = Path(__file__).parents[1]
EXPECTED_FAMILIES = {
    "architecture-design",
    "code-reading",
    "code-review",
    "cross-module-implementation",
    "documentation-maintenance",
    "incident-diagnosis",
    "localized-implementation",
    "protocol-integration",
    "refactoring-planning",
    "test-engineering",
}


def _curated_profiles() -> list[dict]:
    profiles = []
    for path in sorted((PROJECT_ROOT / "agent").glob("*.json")):
        profile = read_profile_file(str(path))
        if "profile_metadata" in profile:
            profiles.append(profile)
    return profiles


def test_curated_profiles_form_ten_strict_ab_provider_pairs():
    profiles = _curated_profiles()
    providers = json.loads(
        (PROJECT_ROOT / "config" / "modelProvider.json").read_text(encoding="utf-8")
    )["providers"]
    catalog = RuntimePolicyCatalog.load(str(PROJECT_ROOT))

    assert len(profiles) == 20
    assert {item["profile_metadata"]["task_family"] for item in profiles} == EXPECTED_FAMILIES

    by_id = {item["id"]: item for item in profiles}
    for family in EXPECTED_FAMILIES:
        pair = [item for item in profiles if item["profile_metadata"]["task_family"] == family]
        assert len(pair) == 2
        assert {item["profile_metadata"]["ab_test"]["variant"] for item in pair} == {"A", "B"}
        assert len({item["fields"]["provider_id"] for item in pair}) == 2
        assert {item["fields"]["runtime_policy"]["policy_id"] for item in pair} == {family}
        assert family in catalog.policies

        comparable_fields = [
            {key: value for key, value in item["fields"].items() if key != "provider_id"}
            for item in pair
        ]
        assert comparable_fields[0] == comparable_fields[1]
        comparison_contracts = [profile_ab_comparison_contract(item) for item in pair]
        assert (
            comparison_contracts[0]["controlled_configuration_sha256"]
            == comparison_contracts[1]["controlled_configuration_sha256"]
        )
        assert {item["variant"] for item in comparison_contracts} == {"A", "B"}

        for item in pair:
            metadata = validate_profile_metadata(item["profile_metadata"])
            peer_id = metadata["ab_test"]["peer_profile_id"]
            peer = by_id[peer_id]
            assert peer["profile_metadata"]["ab_test"]["peer_profile_id"] == item["id"]
            assert peer["profile_metadata"]["ab_test"]["experiment_id"] == metadata["ab_test"]["experiment_id"]
            assert peer["profile_metadata"]["ab_test"]["variant"] != metadata["ab_test"]["variant"]
            assert item["fields"]["provider_id"] in providers
            assert item["fields"]["instruction"].strip()
            assert item["fields"]["system_prompt"].strip()
            assert item["fields"]["tools"] == ["system_tools"]


def test_curated_runtime_policies_have_distinct_task_prompts():
    catalog = RuntimePolicyCatalog.load(str(PROJECT_ROOT))
    selected = {family: catalog.get(family) for family in EXPECTED_FAMILIES}

    assert len({entry.policy.task_direction.code_prompt for entry in selected.values()}) == 10
    assert all(entry.policy.description for entry in selected.values())
    assert selected["localized-implementation"].policy.implementation_checkpoint.evidence_operation_limit == 6
    assert selected["cross-module-implementation"].policy.completion_review.require_done_criteria is True
    assert selected["incident-diagnosis"].policy.implementation_checkpoint.enabled is False
    assert selected["code-review"].policy.implementation_checkpoint.enabled is False


def test_benchmark_runner_records_curated_ab_comparison_contract():
    runner = RunnerSpec(
        runner_id="code-reader-a",
        node_type="agent",
        provider_id="Kimi_CodingPlan",
        profile="agent/CodeReader_Kimi.json",
        runtime_policy_file=None,
    )

    contract = runner_execution_contract(runner)

    assert contract["profile_ab_comparison"]["experiment_id"] == "code-reading-provider-v1"
    assert contract["profile_ab_comparison"]["variant"] == "A"
    assert contract["profile_ab_comparison"]["excluded_variable"] == "fields.provider_id"


def test_benchmark_runner_enforces_curated_ab_pair_contract():
    runners = [
        RunnerSpec(
            runner_id="code-reader-a",
            node_type="agent",
            provider_id="Kimi_CodingPlan",
            profile="agent/CodeReader_Kimi.json",
            runtime_policy_file=None,
        ),
        RunnerSpec(
            runner_id="code-reader-b",
            node_type="agent",
            provider_id="sonnet-5-krill",
            profile="agent/CodeReader_Sonnet.json",
            runtime_policy_file=None,
        ),
    ]
    contracts = [runner_execution_contract(runner) for runner in runners]

    validate_profile_ab_runner_contracts(contracts)

    contracts[1]["profile_ab_comparison"]["controlled_configuration_sha256"] = "changed"
    with pytest.raises(ValueError, match="changes controlled runtime fields"):
        validate_profile_ab_runner_contracts(contracts)


def test_curated_profiles_create_agent_nodes_through_public_api(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from src.web_backend import profile_storage, runtime_paths
    from src.web_backend.facade import WebBackendFacade

    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(runtime_paths, "get_workspace_root", lambda: str(tmp_path))
    shutil.copytree(PROJECT_ROOT / "agent", tmp_path / "agent")
    client = TestClient(WebBackendFacade().build())
    graph_id = "curated_profile_contract"
    graphs_dir = Path(runtime_paths._get_graphs_dir())
    listed_response = client.get("/api/profiles/agents")
    assert listed_response.status_code == 200
    listed_curated = [
        item
        for item in listed_response.json()["profiles"]
        if "profile_metadata" in item
    ]
    assert len(listed_curated) == 20
    assert {
        item["profile_metadata"]["task_family"] for item in listed_curated
    } == EXPECTED_FAMILIES

    for index, profile in enumerate(_curated_profiles()):
        node_id = f"curated_{index:02d}"
        response = client.post(
            f"/api/profiles/agents/{profile['id']}/create",
            json={"graph_id": graph_id, "node_id": node_id},
        )
        assert response.status_code == 200, (profile["id"], response.text)
        config = json.loads(
            (graphs_dir / graph_id / node_id / "config.json").read_text(
                encoding="utf-8"
            )
        )
        assert config["provider_id"] == profile["fields"]["provider_id"]
        assert config["runtime_policy"] == profile["fields"]["runtime_policy"]
        assert config["instruction"] == profile["fields"]["instruction"]
        assert config["system_prompt"] == profile["fields"]["system_prompt"]


def test_profile_metadata_contract_rejects_unknown_or_incomplete_shapes():
    with pytest.raises(ValueError, match="missing required fields"):
        validate_profile_metadata({"schema_version": 1})

    with pytest.raises(ValueError, match="unknown fields"):
        validate_profile_metadata(
            {
                "schema_version": 1,
                "task_family": "code-reading",
                "description": "Read code.",
                "provider_rationale": "Measured.",
                "evidence_level": "measured",
                "recommended_for": [],
                "avoid_for": [],
                "ab_test": {
                    "experiment_id": "code-reading-v1",
                    "variant": "A",
                    "peer_profile_id": "Peer",
                },
                "legacy_label": "not accepted",
            }
        )


def test_all_profile_selection_surfaces_render_curated_choice_summary():
    component = "AgentProfileChoiceSummary"
    sources = [
        PROJECT_ROOT / "webui" / "src" / "components" / "agent-board" / "AgentProfileDropdown.vue",
        PROJECT_ROOT / "webui" / "src" / "components" / "agent-board" / "NodeProfileLoadControl.vue",
        PROJECT_ROOT / "webui" / "src" / "components" / "settings" / "NodeProfilerProfileList.vue",
        PROJECT_ROOT / "webui" / "src" / "mobile" / "MobileNodeProfilePickerSheet.vue",
    ]

    for path in sources:
        assert component in path.read_text(encoding="utf-8"), path
