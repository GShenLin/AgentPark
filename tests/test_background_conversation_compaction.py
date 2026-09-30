import json
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict

import pytest

from nodes.agent_history import load_agent_history_messages
from nodes.agent_history_background import schedule_agent_history_compaction
from src.conversation_context import jobs
from src.conversation_context.checkpoint import FILENAME
from src.conversation_context.settings import ConversationSettings
from src.conversation_context.window import CHECKPOINT_PREFIX
from src.web_backend.node_memory_store import clear_node_memory


@pytest.fixture
def setup_history(tmp_path, monkeypatch):
    coordinator = jobs.CompactionCoordinator()
    monkeypatch.setattr(jobs, "coordinator", coordinator)
    settings = ConversationSettings(input_tokens=4096, retain_tokens=800, summary_tokens=500)
    monkeypatch.setattr("nodes.agent_history_background.ConfigLoader.get_workspace_config",
                        lambda _: {"conversationContext": asdict(settings)})
    monkeypatch.setattr("nodes.agent_history_background.ConfigLoader.get_provider_config",
                        lambda *_: {"type": "openai", "supportmode": ["chat"], "responsesApi": True})
    records = [{"id": f"m{i}", "role": "user" if i % 2 == 0 else "assistant",
                "parts": [{"type": "text", "text": f"turn-{i}: " + "h" * 1200}]}
               for i in range(30)]
    path = tmp_path / "messages.jsonl"

    def write(items):
        path.write_text("".join(json.dumps(r) + "\n" for r in items), encoding="utf-8")

    write(records)
    calls, events = [], []

    def complete(_self, payload):
        calls.append(json.loads(payload))
        return '{"summary":"Earlier facts and constraints"}'

    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", complete)
    context = dict(graph_id="g", node_instance_id="n", task_id="turn",
                   memory_path=str(tmp_path / "memory.md"), messages_path=str(path))

    def schedule(boundary=None, node_type="agent_node"):
        return schedule_agent_history_compaction(
            context=context, config={"type_id": node_type, "provider_id": "test"},
            input_message=records[0], output_message=boundary or records[-1],
            log_event=lambda graph, event, **details: events.append((event, details)),
        )

    def load(current=None, cancel=None):
        return load_agent_history_messages(
            memory_path=context["memory_path"], messages_path=context["messages_path"],
            current_message=current or {"id": "next", "role": "user", "content": "next question"},
            provider_id="test", public_base_url="", settings=settings, cancel_source=cancel,
            historical_evidence_role="developer",
        )

    yield dict(records=records, path=path, write=write, calls=calls, events=events,
               schedule=schedule, load=load, coordinator=coordinator)
    coordinator.shutdown()


def test_post_persist_compaction_is_reused_without_a_model_call_on_next_input(setup_history):
    s = setup_history
    original = s["path"].read_bytes()
    s["schedule"]().result(timeout=5)
    assert s["calls"]
    count = len(s["calls"])
    result = s["load"]()
    assert result[0]["content"].startswith(CHECKPOINT_PREFIX)
    assert result[-1]["content"] == s["records"][-1]["parts"][0]["text"]
    assert len(s["calls"]) == count
    assert s["path"].read_bytes() == original
    assert s["events"][-1][0] == "conversation_compaction_check_completed"


def test_under_budget_post_persist_check_does_not_call_model(setup_history):
    s = setup_history
    s["write"](s["records"][:2])
    s["schedule"](s["records"][1]).result(timeout=5)
    assert not s["calls"]
    assert not (s["path"].parent / FILENAME).exists()


def test_background_snapshot_excludes_new_input_and_future_tool_messages(setup_history):
    s = setup_history
    additions = [{"id": "next", "role": "user", "content": "PRIVATE CURRENT INPUT"},
                 {"id": "tool-new", "role": "tool", "content": "CURRENT TOOL OUTPUT"}]
    s["write"](s["records"] + additions)
    s["schedule"]().result(timeout=5)
    assert "PRIVATE CURRENT INPUT" not in json.dumps(s["calls"])
    assert "CURRENT TOOL OUTPUT" not in json.dumps(s["calls"])
    result = s["load"](additions[0])
    assert result[-1]["content"] == s["records"][-1]["parts"][0]["text"]


def block_model(monkeypatch, calls, started, release, response='{"summary":"Prepared checkpoint"}'):
    def complete(_self, payload):
        calls.append(json.loads(payload))
        started.set()
        assert release.wait(5), "test must release the synthetic model"
        return response
    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", complete)


def test_next_input_does_not_wait_for_running_compaction(setup_history, monkeypatch):
    s = setup_history
    started, release = threading.Event(), threading.Event()
    block_model(monkeypatch, s["calls"], started, release)
    background = s["schedule"]()
    with ThreadPoolExecutor(thread_name_prefix="foreground") as pool:
        try:
            assert started.wait(2)
            result = pool.submit(s["load"]).result(timeout=2)
            assert len(result) == len(s["records"])
            assert result[0]["content"] == s["records"][0]["parts"][0]["text"]
        finally:
            release.set()
        background.result(timeout=5)
    assert s["load"]()[0]["content"].startswith(CHECKPOINT_PREFIX)


def test_failed_background_compaction_does_not_fail_next_input(setup_history, monkeypatch):
    s = setup_history
    started, release = threading.Event(), threading.Event()
    block_model(monkeypatch, s["calls"], started, release, response="invalid json")
    background = s["schedule"]()
    with ThreadPoolExecutor(thread_name_prefix="foreground") as pool:
        try:
            assert started.wait(2)
            result = pool.submit(s["load"]).result(timeout=2)
            assert len(result) == len(s["records"])
        finally:
            release.set()
        with pytest.raises(ValueError):
            background.result(timeout=5)
    assert len(s["load"]()) == len(s["records"])
    assert not (s["path"].parent / FILENAME).exists()


def test_under_budget_input_does_not_wait_for_a_pending_background_job(setup_history):
    s = setup_history
    s["write"](s["records"][:2])
    with s["coordinator"].exclusive(str(s["path"])):
        with ThreadPoolExecutor() as pool:
            result = pool.submit(s["load"]).result(timeout=2)
    assert len(result) == 2
    assert not s["calls"]


@pytest.mark.parametrize("change", ["clear", "edit"])
def test_history_mutation_rejects_stale_background_publication(setup_history, monkeypatch, change):
    s = setup_history
    started, release = threading.Event(), threading.Event()
    block_model(monkeypatch, s["calls"], started, release)
    background = s["schedule"]()
    try:
        assert started.wait(2)
        if change == "clear":
            clear_node_memory(str(s["path"].parent / "memory.md"), str(s["path"]))
        else:
            s["records"][0]["parts"][0]["text"] = "Corrected history"
            s["write"](s["records"])
    finally:
        release.set()
    with pytest.raises(RuntimeError, match="history changed"):
        background.result(timeout=5)
    assert not (s["path"].parent / FILENAME).exists()
    assert s["events"][-1][0] == "conversation_compaction_check_failed"


def test_additional_completed_turn_is_checked_after_running_job(setup_history, monkeypatch):
    s = setup_history
    started, release = threading.Event(), threading.Event()
    block_model(monkeypatch, s["calls"], started, release)
    first = s["schedule"]()
    try:
        assert started.wait(2)
        additions = [{"id": "new-user", "role": "user", "content": "q" * 20000},
                     {"id": "new-assistant", "role": "assistant", "content": "new answer"}]
        s["write"](s["records"] + additions)
        second = s["schedule"](additions[-1])
        assert second is first
    finally:
        release.set()
    first.result(timeout=5)
    assert len([e for e in s["events"] if e[0] == "conversation_compaction_check_completed"]) == 2
    before = len(s["calls"])
    assert s["load"]()[0]["content"].startswith(CHECKPOINT_PREFIX)
    assert len(s["calls"]) == before


def test_failed_background_inference_is_reported_and_history_is_preserved(setup_history, monkeypatch):
    s = setup_history
    original = s["path"].read_bytes()
    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", lambda *_: "invalid json")
    with pytest.raises(ValueError):
        s["schedule"]().result(timeout=5)
    assert s["path"].read_bytes() == original
    assert not (s["path"].parent / FILENAME).exists()
    assert s["events"][-1][0] == "conversation_compaction_check_failed"


def test_non_agent_nodes_do_not_schedule(setup_history):
    assert setup_history["schedule"](node_type="other") is None


def test_media_generation_does_not_compact_conversation(setup_history, monkeypatch):
    s = setup_history
    monkeypatch.setattr("nodes.agent_history_background.ConfigLoader.get_provider_config",
                        lambda *_: {"type": "doubao", "supportmode": ["image_generation"]})
    s["schedule"]().result(timeout=5)
    assert not s["calls"]
    assert s["events"][-1][0] == "conversation_compaction_check_skipped"
