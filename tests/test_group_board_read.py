import json

import pytest
from pydantic import ValidationError

from src.agent_groups.agent_tools import GroupAgentTools
from src.agent_groups.board_read import ReadBoard, ReadBoardDetail, board_detail, board_overview
from src.agent_groups.contracts import AgentGroup, GroupConflict, GroupPermissionError
from src.agent_groups.repository import GroupRepository


def large_board():
    return AgentGroup.model_validate({
        "id": "group", "name": "Game", "objective": "剧情目标" * 8000,
        "bounds": {"x": 0., "y": 0., "width": 100., "height": 100.},
        "members": [{"node_id": f"node-{i}", "role": "关卡作者" * 500} for i in range(23)],
        "tasks": [{"id": f"task-{i}", "title": f"Level {i}", "owner_id": "node-0",
                   "description": "description" * 2000, "evidence": "证据" * 16000,
                   "created_at": "now", "updated_at": "now"} for i in range(27)],
        "created_at": "now", "updated_at": "now",
    })


def test_overview_pages_are_small_and_complete_without_prose_loss():
    group = large_board()
    for kind in ("tasks", "members"):
        found, offset = [], 0
        while offset is not None:
            command = ReadBoard(**{("task_offset" if kind == "tasks" else "member_offset"): offset},
                                expected_revision=group.revision)
            result = board_overview(group, command)
            assert len(json.dumps(result, ensure_ascii=False)) < 20000
            found.extend(result[kind]["items"])
            offset = result[kind]["next_offset"]
        expected = group.tasks if kind == "tasks" else group.members
        assert len(found) == len(expected)
    assert board_overview(group, ReadBoard())["objective_chars"] == 32000
    for section, item_id, expected in [("objective", None, group.objective),
                                      ("task_description", "task-0", group.tasks[0].description),
                                      ("task_evidence", "task-0", group.tasks[0].evidence),
                                      ("member_role", "node-0", group.members[0].role)]:
        parts, offset = [], 0
        while offset is not None:
            result = board_detail(group, ReadBoardDetail(section=section, item_id=item_id,
                                  expected_revision=1, offset=offset))
            assert len(json.dumps(result, ensure_ascii=False)) < 20000
            parts.append(result["text"])
            offset = result["next_offset"]
        assert "".join(parts) == expected


def test_pages_reject_stale_revision_and_invalid_contracts():
    group = large_board()
    with pytest.raises(ValidationError):
        ReadBoard(task_offset=10)
    with pytest.raises(ValidationError):
        ReadBoardDetail(section="task_evidence", expected_revision=1)
    with pytest.raises(GroupConflict):
        board_overview(group, ReadBoard(task_offset=10, expected_revision=2))
    with pytest.raises(GroupConflict):
        board_detail(group, ReadBoardDetail(section="objective", expected_revision=2))
    with pytest.raises(ValueError, match="past the end"):
        board_detail(group, ReadBoardDetail(section="objective", expected_revision=1, offset=32001))


def test_detail_authorizes_current_membership(tmp_path):
    repo = GroupRepository(tmp_path)
    group = large_board()
    with repo.transaction() as db:
        repo.save(db, group, bump=False)
    tools = GroupAgentTools(repo, group.id, "outsider")
    with pytest.raises(GroupPermissionError):
        tools.board_detail(section="task_evidence", item_id="task-0", expected_revision=1)


def test_dependency_pages_do_not_drop_ids():
    group = large_board()
    group.tasks[-1].dependencies = [t.id for t in group.tasks[:-1]]
    found, offset = [], 0
    while offset is not None:
        result = board_detail(group, ReadBoardDetail(section="task_dependencies", item_id="task-26",
                                                    expected_revision=1, offset=offset))
        found.extend(result["items"])
        offset = result["next_offset"]
    assert found == group.tasks[-1].dependencies
