from pathlib import Path

from scripts.provider_benchmark_report import build_provider_report


def test_provider_report_ranks_only_fully_verified_runs():
    suite = {
        "suite_id": "sample",
        "runs": [
            _run("fast-incomplete", duration_ms=1000, completed=False, score=80),
            _run("slower-complete", duration_ms=2000, completed=True, score=100),
        ],
    }
    providers = {
        "fast-incomplete": {"model": "model-a", "type": "openai", "supportmode": ["chat"]},
        "slower-complete": {"model": "model-b", "type": "openai", "supportmode": ["chat"]},
        "image-only": {"model": "image", "type": "doubao", "supportmode": ["image_generation"]},
    }

    report = build_provider_report(suite, providers, source_path=Path("suite-result.json"))

    assert "| 1 | `slower-complete` | `model-b` |" in report
    assert "`fast-incomplete`：输出未满足必选验收项：required" in report
    assert "`image-only`" in report


def _run(provider_id: str, *, duration_ms: int, completed: bool, score: int):
    return {
        "provider_id": provider_id,
        "runner_contract": {
            "profile": {"sha256": "profile"},
        },
        "fixture": {"resolved_revision": "revision"},
        "benchmark": {
            "result": {
                "status": "completed",
                "summary": {
                    "duration_ms": duration_ms,
                    "model_turn_count": 1,
                    "usage_model_turn_count": 1,
                    "missing_usage_model_turn_count": 0,
                    "tool_call_start_count": 0,
                    "failed_tool_call_count": 0,
                    "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
                },
            }
        },
        "verification": {
            "completed": completed,
            "completion_score": score,
            "path_gate_passed": True,
            "required_commands_passed": True,
            "output_checks": [{"id": "required", "passed": completed}],
        },
    }
