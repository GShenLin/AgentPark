import json

import pytest

from nodes.agent_history import load_agent_history_messages
from src.conversation_context.checkpoint import FILENAME, estimate_tokens
from src.conversation_context.settings import ConversationSettings
from src.conversation_context.window import CHECKPOINT_PREFIX, ConversationWindow
from src.web_backend.node_memory_store import clear_node_memory


def history(count=12, size=1200):
    return [{"id": f"m{i}", "role": "user" if i % 2 == 0 else "assistant",
             "parts": [{"type": "text", "text": (f"turn-{i}: " + "z" * size)}]}
            for i in range(count)]


def write_history(folder, records):
    path = folder / "messages.jsonl"
    path.write_text("".join(json.dumps(r) + "\n" for r in records), encoding="utf-8")
    return path


def settings():
    return ConversationSettings(input_tokens=4096, retain_tokens=800, summary_tokens=500)


def load(folder, cfg=None, current=None):
    return load_agent_history_messages(memory_path=str(folder / "memory.md"),
        messages_path=str(folder / "messages.jsonl"), current_message=current or {"id": "new", "role": "user", "content": "continue"},
        provider_id="test", public_base_url="", settings=cfg or settings())


@pytest.fixture
def compactor(monkeypatch):
    calls = []
    def complete(_self, payload):
        calls.append(json.loads(payload))
        return json.dumps({"summary": "Keep the original constraint. Migration failed; verification remains pending."})
    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", complete)
    return calls


def test_more_than_six_messages_remain_verbatim_without_compaction(tmp_path, compactor):
    records = history(30, 10)
    write_history(tmp_path, records)
    result = load(tmp_path)
    assert [r["content"] for r in result] == [r["parts"][0]["text"] for r in records]
    assert not compactor
    assert not (tmp_path / FILENAME).exists()


def test_compaction_restores_checkpoint_and_appended_messages_without_reextracting(tmp_path, compactor):
    records = history(30)
    path = write_history(tmp_path, records)
    original = path.read_bytes()
    first = load(tmp_path)
    assert first[0]["content"].startswith(CHECKPOINT_PREFIX)
    assert estimate_tokens(first) <= settings().input_tokens
    assert first[-1]["content"] == records[-1]["parts"][0]["text"]
    assert path.read_bytes() == original
    assert compactor
    calls = len(compactor)
    additions = history(2, 10)
    for i, item in enumerate(additions):
        item["id"] = f"new-{i}"
    write_history(tmp_path, records + additions)
    restored = load(tmp_path)
    assert restored == first + [{"role": r["role"], "content": r["parts"][0]["text"]} for r in additions]
    assert len(compactor) == calls


def test_current_input_and_queued_future_input_are_not_replayed_or_summarized(tmp_path, compactor):
    records = history(2, 10)
    write_history(tmp_path, records + [{"id": "current", "role": "user", "content": "NOW"},
                                     {"id": "future", "role": "user", "content": "LATER"}])
    result = load(tmp_path, current={"id": "current", "role": "user", "content": "NOW"})
    assert len(result) == 2
    assert "NOW" not in json.dumps(result) and "LATER" not in json.dumps(result)


def test_archive_history_is_included(tmp_path, compactor):
    archive = tmp_path / "archive" / "2026-09-01"
    archive.mkdir(parents=True)
    write_history(archive, [{"id": "old", "role": "user", "content": "original constraint"}])
    write_history(tmp_path, [{"id": "recent", "role": "assistant", "content": "ack"}])
    assert [m["content"] for m in load(tmp_path)] == ["original constraint", "ack"]


def test_history_delete_invalidates_checkpoint_and_clear_removes_it(tmp_path, compactor):
    records = history(30)
    write_history(tmp_path, records)
    load(tmp_path)
    assert (tmp_path / FILENAME).exists()
    write_history(tmp_path, [{"id": "replacement", "role": "user", "content": "new facts"}])
    assert load(tmp_path) == [{"role": "user", "content": "new facts"}]
    clear_node_memory(str(tmp_path / "memory.md"), str(tmp_path / "messages.jsonl"))
    assert not (tmp_path / FILENAME).exists()
    assert load(tmp_path) == []


def test_clear_during_compaction_cannot_resurrect_checkpoint(tmp_path, monkeypatch):
    write_history(tmp_path, history(30))
    def complete(_self, _payload):
        clear_node_memory(str(tmp_path / "memory.md"), str(tmp_path / "messages.jsonl"))
        return '{"summary":"old state"}'
    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", complete)
    with pytest.raises(RuntimeError, match="history changed"):
        load(tmp_path)
    assert not (tmp_path / FILENAME).exists()


@pytest.mark.parametrize("response", ['not json', '{}', '{"summary":""}', '{"summary":[]}', '{"summary":"ok","extra":1}'])
def test_invalid_compaction_never_publishes_or_drops_history(tmp_path, monkeypatch, response):
    path = write_history(tmp_path, history(30))
    before = path.read_bytes()
    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", lambda *_: response)
    with pytest.raises(ValueError):
        load(tmp_path)
    assert path.read_bytes() == before
    assert not (tmp_path / FILENAME).exists()


def test_budget_includes_reserved_current_input_and_tools(tmp_path):
    window = ConversationWindow(tmp_path, settings(), lambda _: pytest.fail("must not call model"))
    with pytest.raises(ValueError, match="current input"):
        window.prepare([], [], reserved_tokens=4000, publish=lambda *_: None)


def test_unicode_segments_cover_full_oversized_history(tmp_path):
    calls = []
    def complete(payload):
        value = json.loads(payload)
        calls.append(value)
        assert estimate_tokens(value) < settings().input_tokens
        return '{"summary":"中文约定"}'
    window = ConversationWindow(tmp_path, settings(), complete)
    text = '中文"反斜线\\' * 8000
    assert window._fold("", text) == "中文约定"
    assert len(calls) > 1
    assert "".join(c["history"] for c in calls) == text


def test_checkpoint_owner_is_node_directory(tmp_path, compactor):
    first, second = tmp_path / "a", tmp_path / "b"
    first.mkdir(); second.mkdir()
    write_history(first, history(30)); write_history(second, [])
    load(first)
    assert load(second) == []
    assert not (second / FILENAME).exists()


@pytest.mark.parametrize("raw", [[], {"input_tokens": True}, {"input_tokens": 1000},
    {"retain_tokens": 0}, {"summary_tokens": 0.5}, {"provider": []}, {"extra": 1},
    {"retain_tokens": 23000}])
def test_context_settings_reject_invalid_contract(raw):
    with pytest.raises(ValueError, match="conversationContext"):
        ConversationSettings.from_config({"conversationContext": raw})
