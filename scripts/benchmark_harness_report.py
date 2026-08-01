from __future__ import annotations

import statistics
from typing import Any

from scripts.benchmark_harness_contract import HarnessSuite


def build_suite_payload(
    suite: HarnessSuite,
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    aggregates = _aggregate_runs(suite, runs)
    return {
        "schema_version": 1,
        "suite_id": suite.suite_id,
        "manifest": str(suite.manifest_path),
        "repetitions": suite.repetitions,
        "run_count": len(runs),
        "runs": runs,
        "aggregates": aggregates,
        "decision": _winner_decision(aggregates),
    }


def _aggregate_runs(
    suite: HarnessSuite,
    runs: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    aggregates: list[dict[str, Any]] = []
    for task in suite.tasks:
        for runner in suite.runners:
            selected = [
                run
                for run in runs
                if run["task_id"] == task.task_id
                and run["runner_id"] == runner.runner_id
            ]
            if not selected:
                continue
            completed = [
                run for run in selected if run["verification"]["completed"]
            ]
            durations = [
                _duration_ms(run)
                for run in completed
                if _duration_ms(run) is not None
            ]
            token_totals = [
                _total_tokens(run)
                for run in selected
                if _total_tokens(run) is not None
            ]
            aggregates.append(
                {
                    "task_id": task.task_id,
                    "runner_id": runner.runner_id,
                    "node_type": runner.node_type,
                    "sample_count": len(selected),
                    "completed_count": len(completed),
                    "completion_rate": len(completed) / len(selected),
                    "mean_completion_score": round(
                        statistics.fmean(
                            run["verification"]["completion_score"]
                            for run in selected
                        ),
                        3,
                    ),
                    "median_duration_ms_completed": (
                        round(statistics.median(durations)) if durations else None
                    ),
                    "median_total_tokens": (
                        round(statistics.median(token_totals))
                        if token_totals
                        else None
                    ),
                }
            )
    return aggregates


def _winner_decision(aggregates: list[dict[str, Any]]) -> dict[str, Any]:
    by_task: dict[str, list[dict[str, Any]]] = {}
    for aggregate in aggregates:
        by_task.setdefault(aggregate["task_id"], []).append(aggregate)
    decisions = []
    for task_id, candidates in sorted(by_task.items()):
        qualified = [
            item
            for item in candidates
            if item["completion_rate"] == 1.0
            and item["median_duration_ms_completed"] is not None
        ]
        winner = min(
            qualified,
            key=lambda item: item["median_duration_ms_completed"],
            default=None,
        )
        decisions.append(
            {
                "task_id": task_id,
                "validated_winner": winner["runner_id"] if winner else None,
                "reason": (
                    "lowest median duration among runners with 100% verified completion"
                    if winner
                    else "no runner achieved 100% verified completion"
                ),
            }
        )
    return {"tasks": decisions}


def render_comparison_markdown(payload: dict[str, Any]) -> str:
    lines = [
        f"# Benchmark suite: {payload['suite_id']}",
        "",
        "| Task | Runner | Verified | Score | Median time | Median tokens |",
        "|---|---|---:|---:|---:|---:|",
    ]
    for item in payload["aggregates"]:
        duration = item["median_duration_ms_completed"]
        duration_text = (
            f"{duration / 1000:.1f}s" if duration is not None else "n/a"
        )
        tokens = item["median_total_tokens"]
        lines.append(
            f"| {item['task_id']} | {item['runner_id']} | "
            f"{item['completed_count']}/{item['sample_count']} | "
            f"{item['mean_completion_score']:.1f} | {duration_text} | "
            f"{tokens if tokens is not None else 'n/a'} |"
        )
    lines.extend(
        [
            "",
            "A speed winner is selected only among runners with 100% verified completion.",
            "",
        ]
    )
    return "\n".join(lines)


def _duration_ms(run: dict[str, Any]) -> int | None:
    summary = (run["benchmark"].get("result") or {}).get("summary") or {}
    value = summary.get("duration_ms")
    return (
        int(value)
        if isinstance(value, int) and not isinstance(value, bool)
        else None
    )


def _total_tokens(run: dict[str, Any]) -> int | None:
    usage = (
        ((run["benchmark"].get("result") or {}).get("summary") or {}).get("usage")
        or {}
    )
    value = usage.get("total_tokens")
    return (
        int(value)
        if isinstance(value, int) and not isinstance(value, bool)
        else None
    )


__all__ = ["build_suite_payload", "render_comparison_markdown"]
