from pathlib import Path

from scripts.benchmark_harness_contract import HarnessSuite
from scripts.benchmark_harness_evidence import runner_execution_contract
from scripts.run_benchmark_suite import _timeout_benchmark_result


PROJECT_ROOT = Path(__file__).parents[1]


def test_provider_comparison_uses_one_profile():
    suites = [
        HarnessSuite.load(PROJECT_ROOT / "benchmarks" / "manifests" / name)
        for name in ("provider-comparison-smoke.json", "provider-comparison-coding.json")
    ]

    assert [len(suite.runners) for suite in suites] == [23, 12]
    for suite in suites:
        assert {runner.profile for runner in suite.runners} == {
            "C:/Project/AgentPark/benchmarks/profiles/provider-comparison.json"
        }

    contracts = [
        runner_execution_contract(runner)
        for suite in suites
        for runner in suite.runners
    ]
    assert {item["profile"]["sha256"] for item in contracts} == {
        contracts[0]["profile"]["sha256"]
    }
    assert {item["runtime_configuration"]["reasoning_effort"] for item in contracts} == {
        ""
    }
    assert {item["provider_id"] for item in contracts} == {
        runner.provider_id for suite in suites for runner in suite.runners
    }


def test_timeout_result_preserves_partial_event_metrics(tmp_path):
    journal = tmp_path / "events.jsonl"
    journal.write_text(
        '{"elapsed_ms":1,"event":{"type":"tool_call_start","name":"inspect"}}\n'
        '{"elapsed_ms":2,"event":{"type":"runtime_notice","stage":"provider_request_completed",'
        '"message":"{\\"request_index\\":1,\\"usage\\":{\\"total_tokens\\":12}}"}}\n',
        encoding="utf-8",
    )

    result = _timeout_benchmark_result(journal, duration_ms=360000, timeout_seconds=360)

    assert result["status"] == "timeout"
    assert result["summary"]["duration_ms"] == 360000
    assert result["summary"]["tool_call_start_count"] == 1
    assert result["summary"]["usage"]["total_tokens"] == 12
