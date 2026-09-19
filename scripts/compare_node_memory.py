"""Live, synthetic-history A/B comparison. No real user histories or credentials are exported.

python -m scripts.compare_node_memory --provider GPT_Official --output artifacts/memory-comparison
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from contextlib import nullcontext

from src.long_term_memory.contracts import encode
from src.long_term_memory.model import ProviderMemoryModel
from src.long_term_memory.pipeline import MemoryPipeline
from src.long_term_memory.prompts import READ_INSTRUCTIONS
from src.long_term_memory.retrieval import MemoryReader
from src.long_term_memory.settings import MemorySettings
from src.long_term_memory.store import MemoryStore
from src.web_backend.node_memory_records import write_jsonl_records


HISTORY = [
    ("cache", "Lumen 项目缓存前缀确定为 lm_orchid_739。已通过读写测试；此约定仅适用于 Lumen。", "已验证并记录，后续 Lumen 缓存操作使用 lm_orchid_739。"),
    ("bucket-old", "Lumen 备份桶先用 archive-north-214。", "记录该临时决定。"),
    ("bucket-correction", "更正昨天的备份桶决定：archive-north-214 已停用，最终使用 archive-east-862。已验证上传和下载。", "已以 archive-east-862 为当前有效决定，旧桶不再使用。"),
    ("migration", "执行 Lumen 数据迁移时遇到 E_LOCK_47，停在迁移前检查，数据库未修改。先不要重试。", "迁移未完成，待处理 E_LOCK_47；尚无成功迁移的证据。"),
    ("preferences", "以后在这个节点讨论方案时，用中文并明确区分已验证事实和推测。", "了解，这作为本节点后续协作的默认方式。"),
]
CASES = [
    {"id": "remote_fact", "question": "Lumen 项目之前验证过的缓存前缀是什么？", "required": ["lm_orchid_739"]},
    {"id": "latest_correction", "question": "Lumen 备份目前最终采用哪个桶？只写当前桶名，不要列历史桶。", "required": ["archive-east-862"], "forbidden": ["archive-north-214"]},
    {"id": "failed_attempt", "question": "之前 Lumen 数据迁移完成了吗，卡在哪里？", "required": ["E_LOCK_47"], "one_of": ["未完成", "没有完成", "未成功", "没完成"]},
    {"id": "scope", "question": "Orion 项目已经确定的缓存前缀是什么？如果历史没有明确记录，请回答不知道，不要沿用其他项目的。", "one_of": ["不知道", "没有", "未", "无法"]},
]


def seed(folder: Path):
    rows = []
    now = time.time()
    for index, (trace, user, answer) in enumerate(HISTORY):
        date = datetime.fromtimestamp(now - (24 - index) * 3600, timezone.utc).isoformat()
        for role, text in (("user", user), ("assistant", answer)):
            rows.append({"id": f"{trace}-{role}", "trace_id": trace, "role": role,
                         "created_at": date, "parts": [{"type": "text", "text": text}]})
    for index in range(30):
        date = datetime.fromtimestamp(now - 60 + index, timezone.utc).isoformat()
        for role, text in (("user", f"把本次编号 {index} 用方括号写出来。"), ("assistant", f"[{index}]")):
            rows.append({"id": f"filler{index}-{role}", "trace_id": f"filler{index}", "role": role,
                         "created_at": date, "parts": [{"type": "text", "text": text}]})
    write_jsonl_records(str(folder / "messages.jsonl"), rows)
    return [{"role": r["role"], "text": r["parts"][0]["text"]} for r in rows[-6:]]


ANSWER_PROMPT = """根据给出的当前问题、近期对话和可选节点记忆回答，未知时明确说不知道。
不要凭常识猜历史事实，不要将其他项目的约定挪用。
每次只返回一个 JSON 对象，不要代码围栏。可选格式：
{"action":"answer","text":"最终回答"}
当 memory_enabled=true 时也可选择：
{"action":"search","query":"具体关键词"}
{"action":"read","source_id":"精确64位十六进制ID，不含memory:前缀","evidence":false}
memory_enabled=false 时没有检索工具，只能回答。每次工具结果会在下一条输入的 observations 中返回。
"""


def answer(model, question, recent, reader=None):
    summary = reader.summary() if reader else ""
    payload = {"question": question, "recent": recent, "memory_enabled": reader is not None,
               "memory": READ_INSTRUCTIONS.format(summary=summary) if reader else "", "observations": []}
    total_bytes = 0
    for _ in range(6):
        total_bytes += len(encode(payload).encode("utf-8"))
        result = json.loads(model.complete("answer", ANSWER_PROMPT, payload))
        action = result.get("action")
        if action == "answer":
            if not isinstance(result.get("text"), str):
                raise ValueError("answer text missing")
            return {"answer": result["text"], "retrievals": payload["observations"], "input_bytes": total_bytes}
        if reader is None:
            raise ValueError("baseline attempted an unavailable tool")
        try:
            if action == "search":
                output = reader.search(result["query"])
            elif action == "read":
                output = reader.read(result["source_id"], evidence=result.get("evidence", False))
            else:
                raise ValueError("unknown evaluation action")
        except ValueError as exc:
            output = {"error": str(exc)}
        payload["observations"].append({"request": result, "result": output})
    raise RuntimeError("evaluation exceeded retrieval budget")


def grade(case, answer_text):
    return (all(value in answer_text for value in case.get("required", []))
            and not any(value in answer_text for value in case.get("forbidden", []))
            and (not case.get("one_of") or any(value in answer_text for value in case["one_of"])))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    model = ProviderMemoryModel(args.provider, args.provider)
    report = {"provider": args.provider, "created_at": datetime.now(timezone.utc).isoformat(),
              "method": "same model and questions; 6 recent messages vs same messages plus node memory and bounded retrieval",
              "synthetic": True, "cases": []}
    start = time.monotonic()
    with nullcontext(args.output / "workspace") as tmp:
        folder = Path(tmp)
        folder.mkdir(parents=True, exist_ok=True)
        if not (folder / "messages.jsonl").exists():
            seed(folder)
        rows = [json.loads(line) for line in (folder / "messages.jsonl").read_text(encoding="utf-8").splitlines()]
        recent = [{"role": r["role"], "text": r["parts"][0]["text"]} for r in rows[-6:]]
        store = MemoryStore(folder, "comparison", "node")
        print("Extracting and consolidating five historical runs...", flush=True)
        with contextlib.redirect_stdout(io.StringIO()):
            report["pipeline"] = MemoryPipeline(store, model, MemorySettings()).run()
        if report["pipeline"]["failed"]:
            with store.connect() as db:
                errors = [dict(r) for r in db.execute("SELECT trace_id,error FROM sources WHERE status='failed'")]
            raise RuntimeError(f"memory extraction failed: {errors}")
        reader = MemoryReader(store)
        report["summary"] = reader.summary()
        report["summary_bytes"] = len(report["summary"].encode("utf-8"))
        (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        for case in CASES:
            record = dict(case)
            for arm, context in (("recent_only", None), ("long_term_memory", reader)):
                print(f"Evaluating {case['id']} / {arm}...", flush=True)
                with contextlib.redirect_stdout(io.StringIO()):
                    result = answer(model, case["question"], recent, context)
                result["passed"] = grade(case, result["answer"])
                record[arm] = result
            report["cases"].append(record)
            (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
        # Delete a source and prove that no published summary or direct read can expose it.
        deleted_id = reader.search("lm_orchid_739")["matches"][0]["source_id"]
        rows = [json.loads(line) for line in (folder / "messages.jsonl").read_text(encoding="utf-8").splitlines()]
        write_jsonl_records(str(folder / "messages.jsonl"), [r for r in rows if r["trace_id"] != "cache"])
        report["deletion_check"] = reader.summary() == "" and reader.search("lm_orchid_739")["matches"] == []
        try:
            reader.read(deleted_id)
            report["deletion_check"] = False
        except ValueError:
            pass
    report["elapsed_seconds"] = round(time.monotonic() - start, 1)
    report["scores"] = {arm: sum(c[arm]["passed"] for c in report["cases"]) for arm in ("recent_only", "long_term_memory")}
    (args.output / "results.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = ["# Node memory comparison", "", f"Provider: {args.provider}. Synthetic histories; one run, not a general benchmark.", "",
             "| Case | Recent 6 messages | Node long-term memory |", "|---|---|---|"]
    for case in report["cases"]:
        lines.append(f"| {case['id']} | {case['recent_only']['passed']} | {case['long_term_memory']['passed']} |")
    lines += ["", f"Summary: {report['summary_bytes']} UTF-8 bytes. Deletion check: {report['deletion_check']}.", "",
              "Exact answers, retrievals and input-byte counts are in results.json. Byte counts are not billed tokens."]
    (args.output / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"scores": report["scores"], "deletion_check": report["deletion_check"], "elapsed_seconds": report["elapsed_seconds"]}), flush=True)


if __name__ == "__main__":
    main()
