"""Run real installed Harnesses against a selected configured Provider in isolated workspaces."""
from __future__ import annotations
import argparse
import json
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.harness.contracts import HarnessContext
from src.harness.process_manager import HarnessProcesses


def probe(harness: str, provider: str, model: str, timeout: float) -> dict:
    root = Path(tempfile.mkdtemp(prefix=f"ap-{harness}-"))
    work = root / "workspace"
    work.mkdir()
    cancel = threading.Event()
    timings = []
    context = HarnessContext(str(root / "config.json"), str(root), {
        "provider_id": provider, "model": model, "working_path": str(work),
        "node_instance_id": root.name, "graph_id": "harness-probe", "timeout_seconds": timeout,
        "cancel_event": cancel, "native_auto_approve": False,
        "web_search": "disabled", "permission_mode": "acceptEdits" if harness == "claude" else "auto",
        "sandbox": "read-only", "instruction": "Read only the requested local probe file. Do not change files or use the network.",
    })
    for turn in range(2):
        nonce = "HARNESS_FILE_" + uuid.uuid4().hex
        (work / "probe.txt").write_text(nonce, encoding="utf-8")
        first = []
        events = []
        started = time.perf_counter()
        def event(value):
            events.append(value)
            if not first and value.get("type") in {"node_message_delta", "node_thinking_delta"}:
                first.append(time.perf_counter() - started)
        context.values["stream_callback"] = event
        timer = threading.Timer(timeout, cancel.set)
        timer.start()
        try:
            result = HarnessProcesses.instance().execute(harness, context,
                "Run a local shell command to read probe.txt in the working directory now. "
                "Actually execute the command using your native shell tool. "
                "The file may have changed since the previous turn. Reply only with its current exact contents.")
            calls = [e for e in events if e.get("type") == "tool_call_end"]
            passed = nonce in result.text
            timings.append({"turn": turn, "nonce_verified": passed,
                "tool_results": len(calls), "first_output_seconds": first[0] if first else None,
                "total_seconds": round(time.perf_counter()-started, 3)})
            if not passed:
                raise RuntimeError("Harness did not return the current file nonce: " + result.text[:800])
        finally:
            timer.cancel()
    return {"status": "passed", "timings": timings, "workspace": str(root)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--harness", action="append", required=True)
    parser.add_argument("--timeout", type=float, default=120)
    parser.add_argument("--output", default=".runtime/harness-live-probe")
    args = parser.parse_args()
    out = Path(args.output).resolve()
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for harness in args.harness:
        row = {"harness": harness, "provider": args.provider, "model": args.model}
        try:
            row.update(probe(harness, args.provider, args.model, args.timeout))
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        rows.append(row)
        (out / f"{harness}.json").write_text(json.dumps(row, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    (out / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    HarnessProcesses.instance().close_all()
    # Close only sessions created in this diagnostic process.
    from nodes.codex_node.runtime.session_manager import CodexSessionManager
    from nodes.claude_node.runtime.session_manager import ClaudeSessionManager
    from src.harness.openclaw_session import OpenClawSessions
    if CodexSessionManager._instance:
        CodexSessionManager._instance.close_all()
    if ClaudeSessionManager._instance:
        ClaudeSessionManager._instance.close_all()
    if OpenClawSessions._instance:
        OpenClawSessions._instance.close_all()
    return int(any(r["status"] != "passed" for r in rows))


if __name__ == "__main__":
    raise SystemExit(main())
