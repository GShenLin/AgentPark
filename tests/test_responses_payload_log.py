import hashlib
import json
from types import SimpleNamespace

from src.providers.responses_payload_log import write_responses_payload_log


def test_responses_payload_log_defaults_to_summary_hash_and_size(tmp_path):
    agent = SimpleNamespace(
        provider_name="openai",
        memory=SimpleNamespace(current_memory_path=str(tmp_path / "memory.md")),
        config={},
    )
    payload = {
        "model": "gpt-test",
        "input": [{"role": "user", "content": "hello"}],
        "tools": [{"type": "function", "name": "read_file"}],
    }
    payload_json = json.dumps(payload, ensure_ascii=False)

    result = write_responses_payload_log(
        agent,
        request_index=1,
        payload=payload,
        payload_json=payload_json,
        request_summary={
            "request_index": 1,
            "input_item_count": 1,
            "approx_input_chars": 5,
            "tools_included_count": 1,
            "input_items": [{"content": "must not be logged"}],
        },
    )

    record = json.loads((tmp_path / "responses_payloads.jsonl").read_text(encoding="utf-8"))
    assert "payload" not in record
    assert record["payload_chars"] == len(payload_json)
    assert record["payload_sha256"] == hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
    assert record["request_summary"] == {
        "request_index": 1,
        "input_item_count": 1,
        "approx_input_chars": 5,
        "tools_included_count": 1,
    }
    assert result["payload_sha256"] == record["payload_sha256"]
