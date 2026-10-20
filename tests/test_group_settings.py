import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from src import workspace_settings
from src.agent_groups.agent_tools import bind_group_tools
from src.agent_groups.contracts import CreateGroup, CreateTask, GroupBounds, GroupMember, PublishMessage, UpdateTask
from src.agent_groups.delivery import GroupDelivery, render_notifications
from src.agent_groups.membership import GroupMembership
from src.agent_groups.messages import GroupMessages
from src.agent_groups.repository import GroupRepository
from src.agent_groups.settings import GroupSettings, group_settings_path, read_group_settings
from src.agent_groups.tasks import GroupTasks
from src.web_backend.settings_api import SettingsApiDomain


@pytest.fixture
def settings_api(monkeypatch, tmp_path):
    monkeypatch.setattr(workspace_settings, "get_workspace_root", lambda: str(tmp_path))
    return SettingsApiDomain(SimpleNamespace())


def save(api, data):
    return api.update_settings_section("group", {"content": json.dumps(data, ensure_ascii=False)})


def team(tmp_path):
    directory = tmp_path / "graph"
    directory.mkdir()
    repo = GroupRepository(directory)
    group = GroupMembership(repo).create(CreateGroup(name="Mixed team",
        bounds=GroupBounds(x=0, y=0, width=600, height=320),
        members=[GroupMember(node_id="a"), GroupMember(node_id="b")]))
    return repo, group


def test_settings_defaults_roundtrip_and_runtime_reload(settings_api):
    loaded = settings_api.get_settings_section("group")
    assert loaded["data"] == loaded["group_defaults"] == GroupSettings().model_dump()
    assert not group_settings_path().exists()
    assert "group" in {s["id"] for s in settings_api.list_settings_sections()["sections"]}
    data = loaded["data"]
    data["context_prompt"] = "按分工执行，提交验证结果。"
    data["notification_prompt"] = "处理最新任务。"
    data["task_notifications"]["assignment"] = False
    saved = save(settings_api, data)
    assert saved["data"] == settings_api.get_settings_section("group")["data"]
    assert read_group_settings().context_prompt == data["context_prompt"]
    assert not read_group_settings().task_notifications.assignment
    data["notification_prompt"] = "下一轮使用的新说明"
    save(settings_api, data)
    rendered = render_notifications([{"seq": 1}])
    assert rendered.startswith("下一轮使用的新说明\n")
    context = json.loads(rendered.split("\n", 1)[1])
    assert context["events"] == [{"seq": 1}]
    assert context["task_notifications"]["assignment"] is False
    save(settings_api, loaded["group_defaults"])
    assert read_group_settings() == GroupSettings()


@pytest.mark.parametrize("data", [
    {"task_notifications": {"assignment": "false"}},
    {"task_notifications": {"dependency_ready": 0}},
    {"context_prompt": None}, {"tool_prompts": {"unknown_tool": "x"}},
    {"unexpected": True}, {"context_prompt": "x" * 32001},
])
def test_invalid_updates_never_replace_saved_settings(settings_api, data):
    save(settings_api, {"context_prompt": "saved"})
    before = group_settings_path().read_bytes()
    with pytest.raises(HTTPException) as error:
        save(settings_api, data)
    assert error.value.status_code == 400
    assert group_settings_path().read_bytes() == before


def test_corrupt_settings_are_reported_without_default_masking(settings_api):
    save(settings_api, {})
    group_settings_path().write_text('{"task_notifications":{"assignment":"bad"}}', encoding="utf-8")
    with pytest.raises(ValidationError):
        read_group_settings()
    with pytest.raises(HTTPException) as error:
        settings_api.get_settings_section("group")
    assert error.value.status_code == 500


def test_custom_prompts_reach_registered_tools_and_member_context(settings_api, tmp_path):
    repo, group = team(tmp_path)
    data = GroupSettings().model_dump()
    data["context_prompt"] = "只处理自己负责的工作"
    data["tool_prompts"] = {key: f"自定义 {key}" for key in data["tool_prompts"]}
    save(settings_api, data)
    tools, messages = {}, []
    agent = SimpleNamespace(
        tools=SimpleNamespace(register_external_tool=lambda schema, fn: tools.update({schema["function"]["name"]: schema["function"]})),
        Message=lambda role, text, **kwargs: messages.append(text),
    )
    assert bind_group_tools(agent, node_directory=str(tmp_path / "graph" / "a"), node_id="a", role="system")
    assert len(tools) == 8
    for name, tool in tools.items():
        assert tool["description"] == data["tool_prompts"][name]
        assert tool["parameters"]["additionalProperties"] is False
    assert messages[0].startswith(data["context_prompt"] + "\n")
    assert json.loads(messages[0].split("\n", 1)[1])["your_node_id"] == "a"


@pytest.mark.parametrize("assignment,dependency", [(False, False), (False, True), (True, False), (True, True)])
def test_notification_switches_change_actual_delivery_recipients(settings_api, tmp_path, assignment, dependency):
    save(settings_api, {"task_notifications": {"assignment": assignment, "dependency_ready": dependency}})
    repo, group = team(tmp_path)
    tasks = GroupTasks(repo)
    first = tasks.create(group.id, CreateTask(title="First", owner_id="a"), None)
    second = tasks.create(group.id, CreateTask(title="Second", owner_id="b", dependencies=[first.id]), None)
    assert {item["node_id"] for item in repo.pending_deliveries()} == ({"a"} if assignment else set())
    tasks.update(group.id, first.id, UpdateTask(expected_revision=1, status="done", evidence="verified"), None)
    assert {item["node_id"] for item in repo.pending_deliveries()} == (
        ({"a"} if assignment else set()) | ({"b"} if dependency else set()))
    # Manual messages still wake members, regardless of task notification policy.
    GroupMessages(repo).publish(group.id, PublishMessage(text="Execute", request_id="manual", recipient_id="b"), None)
    assert "b" in {item["node_id"] for item in repo.pending_deliveries()}


def test_disabling_does_not_cancel_pending_notifications(settings_api, tmp_path):
    save(settings_api, {})
    repo, group = team(tmp_path)
    GroupTasks(repo).create(group.id, CreateTask(title="Ready", owner_id="a"), None)
    delivery = GroupDelivery(repo)
    batch = delivery.batches()[0]
    save(settings_api, {"task_notifications": {"assignment": False}})
    assert delivery.resolve("a", batch["reference"])


def test_empty_prompts_are_intentional_and_partial_documents_are_normalized(settings_api):
    result = save(settings_api, {"context_prompt": "", "tool_prompts": {"group_board": ""}})
    assert result["data"]["context_prompt"] == ""
    assert result["data"]["tool_prompts"]["group_board"] == ""
    assert result["data"]["task_notifications"]["assignment"] is True
