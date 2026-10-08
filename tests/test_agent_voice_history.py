import json

import pytest
from pydantic import ValidationError

from nodes.agent_history import load_agent_history_messages
from src.conversation_context.checkpoint import FILENAME, encode, save_checkpoint
from src.conversation_context.settings import ConversationSettings
from src.conversation_context.window import CHECKPOINT_PREFIX
from src.web_backend.node_voice_records import VoiceFinish, build_voice_record


def text_record(identifier, role, text):
    return {"id": identifier, "role": role, "parts": [{"type": "text", "text": text}]}


def call_record(count=4, size=0):
    return build_voice_record("session", "2026-10-06 23:00:00", VoiceFinish(
        status="ended", duration_ms=count * 1000, lines=[{
            "role": "user" if index % 2 == 0 else "assistant",
            "text": f"语音第{index}句，项目代号青竹。" + "x" * size,
            "offset_ms": index * 1000, "incomplete": index == count - 1,
        } for index in range(count)],
    ))


def write(folder, records):
    (folder / "messages.jsonl").write_text(
        "".join(json.dumps(record, ensure_ascii=False) + "\n" for record in records), encoding="utf-8")


def load(folder, **kwargs):
    return load_agent_history_messages(
        memory_path=str(folder / "memory.md"), messages_path=str(folder / "messages.jsonl"),
        current_message={"id": "current", "role": "user", "content": "刚才通话说了什么？"},
        provider_id="test", public_base_url="", settings=ConversationSettings(
            input_tokens=4096, retain_tokens=800, summary_tokens=500), **kwargs,
    )


def test_saved_call_replays_all_speakers_in_order_and_does_not_rewrite_history(tmp_path):
    call = call_record(65)
    write(tmp_path, [text_record("before", "user", "通话之前"), call,
                     text_record("after", "assistant", "通话之后"),
                     text_record("current", "user", "本次输入不能重复"), call_record()])
    before = (tmp_path / "messages.jsonl").read_bytes()
    messages = load(tmp_path)
    assert len(messages) == 67
    assert messages[0] == {"role": "user", "content": "通话之前"}
    assert messages[-1] == {"role": "assistant", "content": "通话之后"}
    for index, message in enumerate(messages[1:-1]):
        assert message["role"] == call["parts"][0]["data"]["lines"][index]["role"]
        assert message["content"].endswith(f"语音第{index}句，项目代号青竹。")
        assert "语音通话文字记录" in message["content"]
    assert "转写未完成" in messages[-2]["content"]
    assert (tmp_path / "messages.jsonl").read_bytes() == before


def test_voice_boundary_and_empty_calls(tmp_path):
    empty = call_record(0)
    empty["id"] = "voice-empty"
    write(tmp_path, [empty, call_record(), text_record("later", "user", "later")])
    assert len(load(tmp_path, through_message_id="voice-session")) == 4


def test_voice_history_rejects_invalid_speaker_instead_of_elevating_it(tmp_path):
    record = call_record()
    record["parts"][0]["data"]["lines"][0]["role"] = "system"
    write(tmp_path, [record])
    with pytest.raises(ValidationError):
        load(tmp_path)


def test_checkpoint_from_before_voice_projection_cannot_hide_existing_calls(tmp_path):
    before, after = text_record("before", "user", "before"), text_record("after", "assistant", "after")
    write(tmp_path, [before, call_record(), after])
    old_records = [{"id": item["id"], "record": encode({
        "role": item["role"], "parts": item["parts"], "trace_id": None,
    })} for item in (before, after)]
    save_checkpoint(tmp_path, old_records, "旧摘要未包含语音")
    messages = load(tmp_path)
    assert len(messages) == 6
    assert any("青竹" in message["content"] for message in messages)
    assert all("旧摘要未包含语音" not in message["content"] for message in messages)


def test_long_call_uses_existing_compaction_and_edit_invalidates_checkpoint(tmp_path, monkeypatch):
    call = call_record(40, 1100)
    write(tmp_path, [call])
    segments = []

    def complete(_self, payload):
        segments.append(json.loads(payload)["history"])
        return '{"summary":"语音通话约定项目代号为青竹"}'

    monkeypatch.setattr("nodes.agent_history.ConversationModel.complete", complete)
    first = load(tmp_path, prepare_checkpoint=True)
    assert segments and "语音第0句" in "".join(segments)
    assert first[0]["content"].startswith(CHECKPOINT_PREFIX)
    assert "青竹" in first[0]["content"]
    assert (tmp_path / FILENAME).exists()
    assert load(tmp_path) == first
    call["parts"][0]["data"]["lines"][0]["text"] = "代号更正为白鹭"
    write(tmp_path, [call])
    replayed = load(tmp_path)
    assert len(replayed) == 40
    assert "白鹭" in replayed[0]["content"]
    write(tmp_path, [])
    assert load(tmp_path) == []
