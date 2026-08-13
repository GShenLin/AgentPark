from __future__ import annotations

import argparse
import json
import statistics
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def build_provider_report(
    suite: dict[str, Any],
    provider_catalog: dict[str, Any],
    *,
    source_path: Path,
) -> str:
    runs = [item for item in suite.get("runs", []) if isinstance(item, dict)]
    metrics = [_run_metrics(run, provider_catalog) for run in runs]
    contracts = _shared_contracts(runs)
    qualified = sorted(
        (item for item in metrics if item["verified"]),
        key=lambda item: (item["duration_ms"], item["provider_id"]),
    )
    runner_ids = {item["provider_id"] for item in metrics}
    excluded = _excluded_providers(provider_catalog, runner_ids)

    lines = [
        f"# Provider 对比报告：{suite.get('suite_id', 'unknown')}",
        "",
        "## 测试基准",
        "",
        f"- 原始结果：`{source_path}`",
        f"- 样本数：{len(metrics)}；Provider 数：{len(runner_ids)}；完整验收：{len(qualified)}",
        f"- Profile SHA-256：`{contracts['profile_sha256'] or '不一致/缺失'}`",
        f"- fixture revision：`{contracts['fixture_revision'] or '不一致/缺失'}`",
        "- 排名门槛：仅 `benchmark_status=completed` 且全部必选验收、路径门禁通过的样本参与速度排名。",
        "",
        "## 排名摘要",
        "",
    ]
    if qualified:
        lines.extend(
            [
                "| 排名 | Provider | 模型 | 验收分 | 耗时 | 总 token | 模型回合 | 工具调用 |",
                "|---:|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for rank, item in enumerate(qualified, start=1):
            lines.append(
                f"| {rank} | `{item['provider_id']}` | `{item['model']}` | "
                f"{item['score']:.1f} | {_seconds(item['duration_ms'])} | "
                f"{_number(item['total_tokens'], item['usage_complete'])} | "
                f"{item['model_turns']} | {item['tool_calls']} |"
            )
    else:
        lines.append("没有 Provider 通过全部必选验收，因此不产生速度胜者。")

    lines.extend(
        [
            "",
            "## 全量明细",
            "",
            "| Provider | 模型 | 状态 | 验收 | 耗时 | 回合 | 工具/失败 | 输入 | 输出 | 推理 | 缓存命中 | 缓存写入 | 总 token | usage |",
            "|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|",
        ]
    )
    for item in sorted(metrics, key=lambda value: value["provider_id"]):
        lines.append(
            f"| `{item['provider_id']}` | `{item['model']}` | {item['status_text']} | "
            f"{item['score']:.1f} | {_seconds(item['duration_ms'])} | {item['model_turns']} | "
            f"{item['tool_calls']}/{item['failed_tools']} | "
            f"{_token_number(item['input_tokens'], item['usage_status'])} | "
            f"{_token_number(item['output_tokens'], item['usage_status'])} | "
            f"{_token_number(item['reasoning_tokens'], item['usage_status'])} | "
            f"{_token_number(item['cached_tokens'], item['usage_status'])} | "
            f"{_token_number(item['cache_write_tokens'], item['usage_status'])} | "
            f"{_token_number(item['total_tokens'], item['usage_status'], total=True)} | "
            f"{item['usage_status']} |"
        )

    check_ids = sorted(
        {
            str(check.get("id") or "")
            for run in runs
            for check in (run.get("verification", {}).get("output_checks") or [])
            if isinstance(check, dict) and str(check.get("id") or "")
        }
    )
    if check_ids:
        lines.extend(
            [
                "",
                "## 验收项明细",
                "",
                "| Provider | " + " | ".join(check_ids) + " |",
                "|---|" + "---:|" * len(check_ids),
            ]
        )
        for item in sorted(metrics, key=lambda value: value["provider_id"]):
            values = ["通过" if item["checks"].get(check_id) else "未通过" for check_id in check_ids]
            lines.append(f"| `{item['provider_id']}` | " + " | ".join(values) + " |")

    failures = [item for item in metrics if not item["verified"]]
    if failures:
        lines.extend(["", "## 未入榜原因", ""])
        for item in sorted(failures, key=lambda value: value["provider_id"]):
            lines.append(f"- `{item['provider_id']}`：{item['failure_reason']}")

    if excluded:
        lines.extend(
            [
                "",
                "## 未纳入文本编码矩阵",
                "",
                "| Provider | 类型 | 模型 | supportmode |",
                "|---|---|---|---|",
            ]
        )
        for item in excluded:
            lines.append(
                f"| `{item['provider_id']}` | `{item['type']}` | `{item['model']}` | "
                f"`{','.join(item['supportmode'])}` |"
            )

    lines.extend(
        [
            "",
            "## 解读限制",
            "",
            "- 当前 suite 的重复次数决定统计强度；单次样本只能说明本次合同下的观测结果，不能估计方差。",
            "- Token 仅在 Provider 返回 usage 时可直接比较；`部分/缺失` 不应被解释为更省 token，`≥` 表示仅有部分分项。",
            "- 部分 Provider 将 cache-write input 单独返回且不计入 total；报告单列缓存写入，成本分析需按供应商计费规则处理。",
            "- 相同模型经不同 Provider 网关时，结果同时包含模型、网关、缓存、传输协议和服务负载影响。",
            "- 质量是门槛，未完整验收的更短耗时不构成胜出。",
            "",
        ]
    )
    return "\n".join(lines)


def _run_metrics(run: dict[str, Any], providers: dict[str, Any]) -> dict[str, Any]:
    provider_id = str(run.get("provider_id") or run.get("runner_id") or "unknown")
    provider = providers.get(provider_id) if isinstance(providers.get(provider_id), dict) else {}
    verification = run.get("verification") if isinstance(run.get("verification"), dict) else {}
    benchmark = run.get("benchmark") if isinstance(run.get("benchmark"), dict) else {}
    result = benchmark.get("result") if isinstance(benchmark.get("result"), dict) else {}
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    usage = summary.get("usage") if isinstance(summary.get("usage"), dict) else {}
    missing_usage = _integer(summary.get("missing_usage_model_turn_count"))
    model_turns = _integer(summary.get("model_turn_count"))
    usage_complete = model_turns > 0 and missing_usage == 0
    requests = [item for item in (summary.get("requests") or []) if isinstance(item, dict)]
    request_usages = [item.get("usage") for item in requests if isinstance(item.get("usage"), dict)]
    breakdown_complete = usage_complete and len(request_usages) == model_turns and all(
        "input_tokens" in item
        and "output_tokens" in item
        and not (
            _integer(item.get("total_tokens")) > 0
            and _integer(item.get("input_tokens")) + _integer(item.get("output_tokens")) == 0
        )
        for item in request_usages
    )
    if model_turns == 0:
        usage_status = "无模型回合"
    elif not request_usages:
        usage_status = "缺失"
    elif missing_usage > 0:
        usage_status = "部分"
    elif not breakdown_complete:
        usage_status = "总量完整/分项部分"
    else:
        usage_status = "完整"
    benchmark_status = str(result.get("status") or verification.get("benchmark_status") or "error")
    verified = bool(verification.get("completed"))
    checks = {
        str(item.get("id") or ""): bool(item.get("passed"))
        for item in (verification.get("output_checks") or [])
        if isinstance(item, dict)
    }
    error = str(result.get("error") or benchmark.get("stderr") or "").strip()
    failed_checks = [check_id for check_id, passed in checks.items() if not passed]
    if error:
        failure_reason = _classify_error(error)
    elif failed_checks:
        failure_reason = "输出未满足必选验收项：" + "、".join(failed_checks)
    elif not bool(verification.get("path_gate_passed", True)):
        failure_reason = "修改路径门禁未通过"
    elif not bool(verification.get("required_commands_passed", True)):
        failure_reason = "必选验证命令未通过"
    elif not verified:
        failure_reason = f"基准状态为 {benchmark_status}，未达到完整验收"
    else:
        failure_reason = ""
    return {
        "provider_id": provider_id,
        "model": str(provider.get("model") or "unknown"),
        "verified": verified,
        "score": float(verification.get("completion_score") or 0),
        "duration_ms": _integer(summary.get("duration_ms")),
        "model_turns": model_turns,
        "tool_calls": _integer(summary.get("tool_call_start_count")),
        "failed_tools": _integer(summary.get("failed_tool_call_count")),
        "input_tokens": _integer(usage.get("input_tokens")),
        "output_tokens": _integer(usage.get("output_tokens")),
        "reasoning_tokens": _integer(usage.get("reasoning_output_tokens")),
        "cached_tokens": _integer(usage.get("cached_input_tokens")),
        "cache_write_tokens": _integer(usage.get("cache_write_input_tokens")),
        "total_tokens": _integer(usage.get("total_tokens")),
        "usage_complete": usage_complete,
        "usage_status": usage_status,
        "status_text": "完整通过" if verified else benchmark_status,
        "failure_reason": failure_reason,
        "checks": checks,
    }


def _shared_contracts(runs: list[dict[str, Any]]) -> dict[str, str]:
    return {
        "profile_sha256": _single(
            run.get("runner_contract", {}).get("profile", {}).get("sha256") for run in runs
        ),
        "fixture_revision": _single(run.get("fixture", {}).get("resolved_revision") for run in runs),
    }


def _excluded_providers(providers: dict[str, Any], included: set[str]) -> list[dict[str, Any]]:
    output = []
    for provider_id, provider in providers.items():
        if provider_id in included or not isinstance(provider, dict):
            continue
        modes = provider.get("supportmode") if isinstance(provider.get("supportmode"), list) else []
        output.append(
            {
                "provider_id": provider_id,
                "type": str(provider.get("type") or ""),
                "model": str(provider.get("model") or ""),
                "supportmode": [str(item) for item in modes],
            }
        )
    return sorted(output, key=lambda item: item["provider_id"])


def _classify_error(error: str) -> str:
    lowered = error.lower()
    if "reasoning_effort" in lowered:
        return "节点/Provider 推理档位合同不兼容：" + error.splitlines()[0]
    if "401" in lowered or "unauthorized" in lowered or "authentication" in lowered:
        return "鉴权失败：" + error.splitlines()[0]
    if "429" in lowered or "rate limit" in lowered or "quota" in lowered:
        return "限流或额度失败：" + error.splitlines()[0]
    if "timeout" in lowered or "timed out" in lowered:
        return "超时：" + error.splitlines()[0]
    if "400" in lowered or "invalid" in lowered:
        return "请求合同失败：" + error.splitlines()[0]
    return error.splitlines()[0] if error else "未知失败"


def _single(values: Any) -> str:
    unique = {str(value) for value in values if str(value or "").strip()}
    return next(iter(unique)) if len(unique) == 1 else ""


def _integer(value: object) -> int:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else 0


def _seconds(value: int) -> str:
    return f"{value / 1000:.1f}s" if value > 0 else "n/a"


def _number(value: int, complete: bool) -> str:
    if value <= 0 and not complete:
        return "n/a"
    return f"{value:,}"


def _token_number(value: int, status: str, *, total: bool = False) -> str:
    if status in {"缺失", "无模型回合"}:
        return "n/a"
    if total:
        return f"{value:,}" if value > 0 else "n/a"
    if status == "完整":
        return f"{value:,}"
    return f"≥{value:,}" if value > 0 else "n/a"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Render a detailed Provider benchmark report.")
    parser.add_argument("--suite-result", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    source = Path(args.suite_result).resolve()
    output = Path(args.output).resolve()
    suite = _read_object(source)
    catalog_root = _read_object(PROJECT_ROOT / "config" / "modelProvider.json")
    providers = catalog_root.get("providers")
    if not isinstance(providers, dict):
        raise ValueError("config/modelProvider.json providers must be an object")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        build_provider_report(suite, providers, source_path=source),
        encoding="utf-8",
    )
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
