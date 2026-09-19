import threading
import time
from pathlib import Path

import httpx
import pytest

from src.knowledge.contracts import LibraryConfig
from src.knowledge.database import Database
from src.knowledge.embedding import Embedder
from src.knowledge.pipeline import ParseAhead
from src.knowledge.scanner import begin_scan, scan, prune


def prepared(tmp_path, count=6):
    folder = tmp_path / "notes"
    folder.mkdir()
    for i in range(count):
        (folder / f"{i}.md").write_text("cats and knowledge", encoding="utf-8")
    config = LibraryConfig(name="test", folder=str(folder), embedding_url="http://localhost/v1",
                           embedding_model="test", dimensions=8)
    store = Database(tmp_path / "index")
    store.initialize()
    stop = threading.Event()
    begin_scan(store); scan(store, folder, stop); prune(store, stop)
    return config, store, stop


def test_parser_progresses_during_real_429_retry_wait(tmp_path, monkeypatch):
    config, store, stop = prepared(tmp_path)
    rate_limited = threading.Event()
    real_parse = __import__("src.knowledge.pipeline", fromlist=["parse_pending"]).parse_pending

    def parse_after_429(*args, **kwargs):
        assert rate_limited.wait(5)
        return real_parse(*args, **kwargs)

    monkeypatch.setattr("src.knowledge.pipeline.parse_pending", parse_after_429)
    requests = []

    def respond(request):
        requests.append(request.content)
        if len(requests) == 1:
            rate_limited.set()
            return httpx.Response(429)
        assert store.status()["documents"]["embedding"] == 6
        return httpx.Response(200, json={"data": [{"index": 0, "embedding": [1.0] * 8}]})

    client_type = httpx.Client
    monkeypatch.setattr("src.knowledge.embedding.httpx.Client", lambda **kwargs: client_type(
        transport=httpx.MockTransport(respond), **kwargs))
    with ParseAhead(store, config, stop) as parser:
        assert Embedder(config, stop=parser.stop).embed(["query"]) == [[1.0] * 8]
    assert len(requests) == 2 and requests[0] == requests[1]


def test_queue_cap_and_pause_leave_resumable_documents(tmp_path):
    config, store, stop = prepared(tmp_path)
    with ParseAhead(store, config, stop, max_pending_chunks=2) as parser:
        deadline = time.monotonic() + 5
        while store.status()["documents"].get("embedding", 0) < 2 and time.monotonic() < deadline:
            time.sleep(0.02)
        time.sleep(0.2)
        assert store.status()["documents"]["embedding"] == 2
        assert store.status()["documents"]["pending"] == 4
        stop.set()
    assert not parser.thread.is_alive()


def test_parse_failure_is_propagated_and_stops_embedding(tmp_path, monkeypatch):
    config, store, stop = prepared(tmp_path)

    def fail(*args, **kwargs):
        raise RuntimeError("storage unavailable")

    monkeypatch.setattr("src.knowledge.pipeline.parse_pending", fail)
    with pytest.raises(RuntimeError, match="storage unavailable"):
        with ParseAhead(store, config, stop) as parser:
            assert parser.done.wait(5)
            assert parser.stop.is_set()
