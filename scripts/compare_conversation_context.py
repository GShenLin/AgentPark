"""Live synthetic comparison of the former six-message window and persistent compaction."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import time

from nodes.agent_history import load_agent_history_messages
from src.conversation_context.checkpoint import FILENAME, estimate_tokens
from src.conversation_context.settings import ConversationSettings
from src.providers import create_agent
from src.providers.agent_runtime_context import AgentRuntimeContext, bind_agent_runtime_context


def records():
    items = []
    def add(role, content):
        items.append({"id": f"synthetic-{len(items)}", "role": role,
                      "created_at": "2026-09-09T10:00:00+00:00", "content": content})
    add("user", "Project Nova: use cache key nova_azalea_472 and backup bucket nova-west-381. Never deploy before I approve.")
    add("assistant", "Acknowledged. Approval is required before deployment.")
    add("user", "Correction: replace that backup bucket with nova-east-926. The west bucket is obsolete.")
    add("assistant", "The backup bucket is now nova-east-926; the cache key remains unchanged.")
    add("user", "Migration attempt returned E_LOCK_63 and did not complete. Next action: inspect the lock owner; do not deploy.")
    add("assistant", "Migration failed. I will inspect the lock owner next and await approval before any deployment.")
    for index in range(24):
        add("user", f"Unrelated typography exercise {index}. " + "Compare readability, spacing, and letter shapes in this sample. " * 18)
        add("assistant", f"Exercise {index}: spacing and letter shape are the only subjects here. " + "No project actions occurred. " * 8)
    return items


def answer(provider, folder, history):
    prompt = ('Answer from the supplied conversation only. Return ONLY JSON with keys cache, bucket, status, next_action. '
              'Use exact identifiers for cache and bucket. status must be "failed", "succeeded", or null. '
              'next_action must be "inspect_lock_owner", "deploy", or null. Unknown values must be null.')
    agent = create_agent(provider, memory_file_path=str(folder / "answer.md"), system_prompt=prompt,
                         internal_memory_enabled=False)
    bind_agent_runtime_context(agent, AgentRuntimeContext(responses_instruction=prompt, task_id="context-comparison"))
    for message in history:
        agent.Message(message["role"], message["content"], persist=False)
    agent.Message("user", "For Project Nova, what are the cache key, current backup bucket, migration status and immediate next action?", persist=False)
    return json.loads(agent.Send(run_tools=False, thinking="enabled", reasoning_effort="low", stream=False))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--provider", default="GPT_Official")
    parser.add_argument("--output", default="artifacts/conversation-context-comparison")
    args = parser.parse_args()
    started = time.monotonic()
    with TemporaryDirectory(prefix="agentpark-context-comparison-") as temp:
        folder = Path(temp)
        source = records()
        (folder / "messages.jsonl").write_text("".join(json.dumps(item) + "\n" for item in source), encoding="utf-8")
        cfg = ConversationSettings(input_tokens=6000, retain_tokens=1000, summary_tokens=1000, provider=args.provider)
        kwargs = dict(memory_path=str(folder / "memory.md"), messages_path=str(folder / "messages.jsonl"),
                      current_message={"id": "current", "role": "user", "content": "continue"},
                      provider_id=args.provider, public_base_url="", settings=cfg, reserved_tokens=500)
        print("Compacting synthetic conversation...", flush=True)
        window = load_agent_history_messages(**kwargs)
        checkpoint = json.loads((folder / FILENAME).read_text(encoding="utf-8"))
        restored = load_agent_history_messages(**kwargs)
        assert window == restored, "reopening must restore exactly the same compacted conversation"
        print("Comparing answers after restoration...", flush=True)
        baseline = answer(args.provider, folder, source[-6:])
        compacted = answer(args.provider, folder, restored)
        expected = {"cache": "nova_azalea_472", "bucket": "nova-east-926", "status": "failed", "next_action": "inspect_lock_owner"}
        result = {
            "provider": args.provider, "synthetic_only": True, "elapsed_seconds": round(time.monotonic() - started, 2),
            "source_messages": len(source), "window_estimated_tokens": estimate_tokens(window),
            "checkpoint": checkpoint, "reopen_equal": window == restored,
            "baseline": baseline, "compacted": compacted, "expected": expected,
            "baseline_score": sum(baseline.get(k) == v for k, v in expected.items()),
            "compacted_score": sum(compacted.get(k) == v for k, v in expected.items()),
        }
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "results.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output / "report.md").write_text(
        "# Conversation context comparison\n\nSynthetic history; one run, not a general benchmark.\n\n"
        f"- Original history: {result['source_messages']} messages.\n"
        f"- Former six-message window: {result['baseline_score']}/4.\n"
        f"- Compacted and restored window: {result['compacted_score']}/4.\n"
        f"- Restored window equals initial compacted window: {result['reopen_equal']}.\n"
        f"- Estimated window tokens: {result['window_estimated_tokens']} (UTF-8 bytes / 4).\n",
        encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("baseline_score", "compacted_score", "elapsed_seconds", "reopen_equal")}), flush=True)
    if result["compacted_score"] != 4:
        raise SystemExit("compacted conversation failed the factual recall checks")


if __name__ == "__main__":
    main()
