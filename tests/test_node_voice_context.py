import json
import time
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src.web_backend.node_voice import NodeVoiceApi, VoiceDelegation, VoiceLease
from src.web_backend.node_voice_context import context_cursor, context_updates
from src.web_backend.node_memory_store import append_node_memory_entry


@pytest.fixture
def context(tmp_path):
    runtime = SimpleNamespace(
        _node_memory_path=lambda *_: str(tmp_path / "memory.md"),
        _node_messages_path=lambda *_: str(tmp_path / "messages.jsonl"),
        _sanitize_graph_id=lambda value: value,
    )
    def append(id, role="user", text="hello", parts=None):
        record = {"id": id, "role": role, "parts": parts or [{"type": "text", "text": text}],
                  "created_at": "2026-10-12 21:00:00.000000"}
        append_node_memory_entry(runtime._node_memory_path(), runtime._node_messages_path(), role, record)
    return runtime, append


def test_cursor_preserves_handshake_updates_and_skips_private_metadata(context):
    runtime, append = context
    append("before")
    cursor = context_cursor(runtime, "node", "graph")
    append("secret", "metadata", "private provider payload")
    append("tool", "tool", "private tool data")
    append("during-offer", "assistant", "new answer")
    page = context_updates(runtime, "node", "graph", cursor)
    assert page == {"cursor": "during-offer", "messages": [
        {"id": "during-offer", "role": "assistant", "parts": [{"type": "text", "text": "new answer"}]},
    ]}
    assert context_updates(runtime, "node", "graph", cursor) == page
    assert context_updates(runtime, "node", "graph", page["cursor"])["messages"] == []


def test_complete_long_results_and_order_survive_multiple_pages(context):
    runtime, append = context
    text = "中文结果" * 9000
    append("long", "assistant", text)
    for i in range(35):
        append(str(i))
    first = context_updates(runtime, "n", "g", "")
    assert len(first["messages"]) == 32
    assert first["messages"][0]["parts"][0]["text"] == text
    second = context_updates(runtime, "n", "g", first["cursor"])
    assert [m["id"] for m in first["messages"] + second["messages"]] == ["long", *map(str, range(35))]


def test_missing_cursor_is_an_explicit_gap_not_silent_history_loss(context):
    runtime, append = context
    append("replacement")
    with pytest.raises(HTTPException) as error:
        context_updates(runtime, "node", "graph", "deleted")
    assert error.value.status_code == 409


def test_resource_projection_excludes_internal_metadata(context):
    runtime, append = context
    append("image", parts=[{"type": "resource", "resource": {
        "uri": "image.png", "kind": "image", "name": "image.png", "metadata": {"private": "hidden"},
    }}])
    page = context_updates(runtime, "node", "graph", "")
    assert "hidden" not in json.dumps(page)
    assert page["messages"][0]["parts"][0]["resource"]["uri"] == "image.png"


def test_context_requires_live_owned_lease_and_visibility(context):
    runtime, append = context
    append("latest")
    ops = SimpleNamespace(require_node_visible=Mock(), enqueue_node_instance_pending=Mock())
    service = NodeVoiceApi(SimpleNamespace(graph_runtime=runtime, node_ops=ops,
        access_api=SimpleNamespace(message_access_metadata=lambda owner: {"_access_client_id": owner})))
    service._leases["s"] = VoiceLease("n", "g", "owner", time.monotonic() + 60)
    assert service.context("n", "s", "owner", "g")["cursor"] == "latest"
    for node, graph, owner in [("other", "g", "owner"), ("n", "other", "owner"), ("n", "g", "other")]:
        with pytest.raises(HTTPException):
            service.context(node, "s", owner, graph)
    ops.require_node_visible.side_effect = HTTPException(404, "private")
    with pytest.raises(HTTPException):
        service.context("n", "s", "owner", "g")


def test_draft_is_typed_and_delegates_all_attachment_kinds_once(context):
    runtime, _ = context
    ops = SimpleNamespace(require_node_visible=Mock(), enqueue_node_instance_pending=Mock())
    service = NodeVoiceApi(SimpleNamespace(graph_runtime=runtime, node_ops=ops,
        access_api=SimpleNamespace(message_access_metadata=lambda owner: {"_access_client_id": owner})))
    service._leases["s"] = VoiceLease("n", "g", "owner", time.monotonic() + 60)
    draft = {"text": "未发送的笔记", "resources": [
        {"uri": name, "name": name, "kind": kind, "mime": mime, "source": "voice_composer"}
        for name, kind, mime in [("image.png", "image", "image/png"), ("clip.mp4", "video", "video/mp4"),
                                  ("report.pdf", "doc", "application/pdf"), ("data.csv", "file", "text/csv")]
    ]}
    payload = VoiceDelegation(delegation_id="draft", text="解释这些资料", composer=draft)
    first = service.delegate("n", "s", payload, "owner", "g")
    assert service.delegate("n", "s", payload, "owner", "g")["request_id"] == first["request_id"]
    ops.enqueue_node_instance_pending.assert_called_once()
    message = ops.enqueue_node_instance_pending.call_args.args[1]["payload"]
    assert "未发送的笔记" in message["parts"][0]["text"]
    assert [p["resource"]["kind"] for p in message["parts"][1:]] == ["image", "video", "doc", "file"]
    assert draft["text"] == "未发送的笔记"
    changed = payload.model_copy(update={"text": "不同请求"})
    with pytest.raises(HTTPException) as error:
        service.delegate("n", "s", changed, "owner", "g")
    assert error.value.status_code == 409
    with pytest.raises(ValidationError):
        VoiceDelegation(delegation_id="x", text="read", composer={**draft, "role": "system"})


def test_draft_image_enters_existing_multimodal_path(context, tmp_path):
    from nodes.agent_message_adapter import build_agent_user_content
    from src.web_backend.node_voice_draft import VoiceDraft
    image = tmp_path / "picture.png"
    image.write_bytes(b"actual image bytes")
    draft = VoiceDraft(text="描述图片和视频", resources=[
        {"uri": str(image), "name": image.name, "kind": "image", "mime": "image/png", "source": "voice_composer"},
        {"uri": "clip.mp4", "name": "clip.mp4", "kind": "video", "mime": "video/mp4", "source": "voice_composer"},
    ])
    content = build_agent_user_content("GPT_Official", "chat", draft.message("查看资料"))
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")
    assert "[video] clip.mp4" in content[0]["text"]
    assert "必须读取实际附件内容" in content[0]["text"]
