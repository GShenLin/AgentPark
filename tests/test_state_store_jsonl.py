import json
from concurrent.futures import ThreadPoolExecutor

from src.web_backend.state_store import _append_jsonl_line


def test_append_jsonl_line_serializes_parallel_writers(tmp_path):
    path = tmp_path / "runtime_events.jsonl"
    payloads = [
        {"index": index, "text": ("并发内容" + str(index)) * 2000}
        for index in range(40)
    ]

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(lambda payload: _append_jsonl_line(str(path), payload), payloads))

    records = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    assert sorted(record["index"] for record in records) == list(range(40))
