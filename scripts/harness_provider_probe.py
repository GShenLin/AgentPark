"""Opt-in paid-model protocol matrix for Harness gateways; executes no model code.

python scripts/harness_provider_probe.py --provider deepseek --model deepseek-v4-flash
python scripts/harness_provider_probe.py --all-configured
Results contain synthetic prompts only, never credentials. Each case requires a
structured tool call, returns a fresh nonce, and verifies the model uses it.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import json
from pathlib import Path
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.config_loader import ConfigLoader
from src.cli_provider_runtime.gateway_dispatch import dispatch_responses, dispatch_messages
from src.cli_provider_runtime.provider_adapter import provider_protocol
from src.cli_provider_runtime.responses_stream import collect_responses_stream


def request(case: str) -> dict:
    instruction = "Protocol test. Call read_probe exactly once with no arguments. After receiving its result, reply with that result exactly."
    schema = {"type": "object", "properties": {}, "additionalProperties": False}
    if case == "messages":
        return {"model": "test", "stream": True, "max_tokens": 2048,
                "messages": [{"role": "user", "content": instruction}],
                "tools": [{"name": "read_probe", "description": "Read the test value.", "input_schema": schema}]}
    payload = {"model": "test", "stream": True, "store": False,
               "input": [{"role": "user", "content": instruction}]}
    if case == "responses":
        payload["tools"] = [{"type": "function", "name": "read_probe",
                             "description": "Read the test value.", "parameters": schema}]
    else:
        payload["input"][0]["content"] = (
            "Protocol test. Call functions.exec exactly once with the raw string read_probe. "
            "After receiving the tool result, reply with that result exactly.")
        payload["input"].insert(0, {"type": "additional_tools", "role": "developer", "tools": [
            {"type": "namespace", "name": "functions", "description": "Protocol test tools", "tools": [
                {"type": "custom", "name": "exec", "description": "Read a test value. Input must be read_probe.",
                 "format": {"type": "text"}}]}]})
    return payload


def send(config: dict, payload: dict, case: str) -> dict:
    result = (dispatch_messages if case == "messages" else dispatch_responses)(config, payload)
    if result.json_body is not None:
        return result.json_body
    if case != "messages":
        return collect_responses_stream(result.stream)
    blocks = {}
    stopped = False
    for chunk in result.stream:
        for line in chunk.decode("utf-8").splitlines():
            if not line.startswith("data: {"):
                continue
            event = json.loads(line[6:])
            kind = event.get("type")
            if kind == "content_block_start":
                blocks[event["index"]] = copy.deepcopy(event["content_block"])
            elif kind == "content_block_delta":
                block = blocks[event["index"]]
                delta = event["delta"]
                if delta["type"] == "text_delta":
                    block["text"] = block.get("text", "") + delta["text"]
                elif delta["type"] == "input_json_delta":
                    block["_json"] = block.get("_json", "") + delta["partial_json"]
            elif kind == "error":
                raise RuntimeError(str(event["error"]))
            elif kind == "message_stop":
                stopped = True
    if not stopped:
        raise RuntimeError("Messages stream ended without message_stop")
    for block in blocks.values():
        if "_json" in block:
            block["input"] = json.loads(block.pop("_json"))
    return {"role": "assistant", "content": list(blocks.values())}


def probe(config: dict, case: str) -> dict:
    payload = request(case)
    first = send(config, payload, case)
    nonce = "HARNESS_PROBE_" + uuid.uuid4().hex
    output = first.get("content", []) if case == "messages" else first.get("output", [])
    calls = [item for item in output if item.get("type") in {"tool_use", "function_call", "custom_tool_call"}]
    if len(calls) != 1:
        raise AssertionError(f"Expected one structured call, received {len(calls)}; output types={[x.get('type') for x in output]}")
    call = calls[0]
    if case == "lite":
        assert (call["type"], call["name"], call["input"].strip()) == (
            "custom_tool_call", "exec", "read_probe"), "Custom tool identity/input changed"
        if config["type"] in {"doubao", "deepseek", "grok"}:
            assert call.get("namespace") == "functions", "Flattened tool namespace was not restored"
    else:
        assert call["name"] == "read_probe", "Unexpected tool name"
        args = call["input"] if case == "messages" else json.loads(call["arguments"])
        assert args == {}, "Unexpected tool arguments"
    if case == "messages":
        payload["messages"].extend([first, {"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": call["id"], "content": nonce}]}])
    else:
        payload["input"].extend(output)
        payload["input"].append({"type": "custom_tool_call_output" if case == "lite" else "function_call_output",
                                 "call_id": call["call_id"], "output": nonce})
    second = send(config, payload, case)
    if case == "messages":
        text = "".join(x.get("text", "") for x in second["content"] if x.get("type") == "text")
    else:
        text = second["output_text"]
    assert text.strip() == nonce, "Final answer did not match the tool result"
    return {"tool_roundtrip": True, "final_nonce_verified": True, "model_requests": 2}


def run_provider(provider: str, model: str, output: Path) -> list[dict]:
    rows = []
    try:
        config = ConfigLoader().get_provider_config(provider)
        if model:
            config["model"] = model
        protocol = provider_protocol(config)
    except Exception as exc:
        return [{"provider": provider, "status": "error", "error": str(exc)}]
    # Bound diagnostic time/retries without changing the saved Provider settings.
    config.update(maxRetries=0, timeoutMs=60000)
    for case in ("responses", "lite", "messages"):
        row = {"provider": provider, "type": config["type"], "model": config["model"],
               "protocol": protocol, "case": case}
        started = time.monotonic()
        try:
            row.update(probe(config, case), status="passed")
        except Exception as exc:
            row.update(status="failed", error=f"{type(exc).__name__}: {exc}")
        row["seconds"] = round(time.monotonic() - started, 2)
        rows.append(row)
        (output / (provider + ".json")).write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        print(json.dumps(row, ensure_ascii=True), flush=True)
    return rows


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--provider", action="append")
    group.add_argument("--all-configured", action="store_true")
    parser.add_argument("--model", default="")
    parser.add_argument("--output", default=".runtime/harness-provider-matrix")
    args = parser.parse_args()
    if args.all_configured and args.model:
        parser.error("--model requires --provider")
    output = Path(args.output)
    output.mkdir(parents=True, exist_ok=True)
    if args.all_configured:
        document = json.loads(Path(ConfigLoader().get_provider_config_path()).read_text(encoding="utf-8"))
        providers = [key for key, value in document["providers"].items() if "chat" in value.get("supportmode", [])]
    else:
        providers = args.provider
    rows = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futures = [pool.submit(run_provider, key, args.model, output) for key in providers]
        for future in as_completed(futures):
            rows.extend(future.result())
    (output / "summary.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    return int(any(row["status"] != "passed" for row in rows))


if __name__ == "__main__":
    raise SystemExit(main())
