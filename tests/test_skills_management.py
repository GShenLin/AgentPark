import json
import os
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodes.agent_skill_loader import list_available_skill_options
from src.skills.references import references_under
from src.skills.roots import root_id
from src.web_backend.skills_api import SkillOperation, SkillsApi


def write_skill(root, path, description="设计游戏机制", body="# 使用说明\n\n完整说明"):
    folder = root / path
    folder.mkdir(parents=True)
    (folder / "SKILL.md").write_text(
        f"---\nname: Design\ndescription: {description}\nversion: 1.2.0\n---\n{body}", encoding="utf-8",
    )
    return folder


@pytest.fixture
def setup(tmp_path):
    root = tmp_path / ".agents" / "skills"
    root.mkdir(parents=True)
    api = SkillsApi(root, tmp_path, tmp_path / "memories")
    app = FastAPI()
    app.get("/api/skills")(api.list_skills)
    app.get("/api/skills/detail")(api.detail)
    app.post("/api/skills/operations")(api.operate)
    return root, api, TestClient(app)


def test_nested_inventory_counts_empty_folders_and_full_detail(setup):
    root, api, client = setup
    folder = write_skill(root, "Game/Design/combat")
    write_skill(root, "Game/Design/economy")
    (root / "Empty").mkdir()
    (folder / "scripts").mkdir()
    (folder / "scripts" / "helper.py").write_text("print('ok')", encoding="utf-8")
    entries = {item["path"]: item for item in api.list_skills()["sources"][0]["entries"]}
    assert entries["Game"]["skill_count"] == 2
    assert entries["Game"]["folder_count"] == 1
    assert entries["Empty"]["skill_count"] == 0
    assert "Game/Design/combat/scripts" not in entries
    assert entries["Game/Design/combat"]["description"] == "设计游戏机制"
    response = client.get("/api/skills/detail", params={"root_id": root_id(root), "path": "Game/Design/combat"})
    assert response.status_code == 200
    assert "完整说明" in response.json()["content"]
    assert response.json()["resources"][0]["path"] == "scripts/helper.py"


def test_malformed_skill_remains_visible_and_raw_document_readable(setup):
    root, api, client = setup
    folder = write_skill(root, "broken")
    (folder / "SKILL.md").write_text("Not frontmatter", encoding="utf-8")
    assert api.list_skills()["sources"][0]["entries"][0]["error"]
    result = client.get("/api/skills/detail", params={"root_id": root_id(root), "path": "broken"}).json()
    assert result["content"] == "Not frontmatter"
    assert result["error"]


def test_move_bundle_invalidates_discovery_and_keeps_all_files(setup):
    root, api, client = setup
    folder = write_skill(root, "demo")
    (folder / "asset.bin").write_bytes(b"\x00\xff")
    assert list_available_skill_options(str(root))[0]["value"] == "demo"
    api.operate(SkillOperation(root_id=root_id(root), action="create_folder", name="Game"))
    api.operate(SkillOperation(root_id=root_id(root), action="create_folder", parent="Game", name="Design"))
    response = client.post("/api/skills/operations", json={"root_id": root_id(root), "action": "move", "path": "demo", "parent": "Game/Design", "name": "combat"})
    assert response.status_code == 200
    assert (root / "Game/Design/combat/asset.bin").read_bytes() == b"\x00\xff"
    assert list_available_skill_options(str(root))[0]["value"] == "Game/Design/combat"


def test_delete_and_restore_entire_category_without_overwrite(setup):
    root, api, client = setup
    write_skill(root, "Game/Design/demo")
    response = client.post("/api/skills/operations", json={"root_id": root_id(root), "action": "delete", "path": "Game"})
    assert response.status_code == 200
    assert not (root / "Game").exists()
    record = api.list_skills()["sources"][0]["trash"][0]
    (root / "Game").mkdir()
    response = client.post("/api/skills/operations", json={"root_id": root_id(root), "action": "restore", "trash_id": record["id"]})
    assert response.status_code == 409
    (root / "Game").rmdir()
    api.operate(SkillOperation(root_id=root_id(root), action="restore", trash_id=record["id"]))
    assert (root / "Game/Design/demo/SKILL.md").exists()
    assert api.list_skills()["sources"][0]["trash"] == []


@pytest.mark.parametrize("path", ["../outside", "/outside", "C:/outside", "Game/../other", "", " Game", "CON", "Game.", "Game//a", "a\\b"])
def test_unsafe_paths_are_rejected(setup, path):
    root, api, client = setup
    response = client.post("/api/skills/operations", json={"root_id": root_id(root), "action": "delete", "path": path})
    assert response.status_code == 400
    assert root.exists()


def test_reject_self_descendant_overwrite_and_inside_bundle(setup):
    root, api, client = setup
    write_skill(root, "Game/demo")
    write_skill(root, "other")
    (root / "Game/Design").mkdir()
    for operation, code in [
        ({"root_id": root_id(root), "action": "move", "path": "Game", "parent": "Game/Design", "name": "Game"}, 400),
        ({"root_id": root_id(root), "action": "move", "path": "other", "parent": "Game", "name": "demo"}, 409),
        ({"root_id": root_id(root), "action": "create_folder", "parent": "Game/demo", "name": "Nested"}, 400),
    ]:
        assert client.post("/api/skills/operations", json=operation).status_code == code
    assert (root / "other/SKILL.md").exists()


@pytest.mark.parametrize("location,payload", [
    ("agent/demo.json", {"skills": ["Game/demo"]}),
    ("graph/template.json", {"nodes": [{"config": {"skills": ["Game\\demo"]}}]}),
    ("memories/Companion/Companion/config.json", {"skills": ["Game/demo"]}),
])
def test_in_use_category_is_blocked_and_shows_reference(setup, location, payload):
    root, api, client = setup
    write_skill(root, "Game/demo")
    config = api.workspace / location
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps(payload), encoding="utf-8")
    assert api.list_skills()["sources"][0]["entries"][0]["used_by"]
    for operation in [
        {"root_id": root_id(root), "action": "delete", "path": "Game"},
        {"root_id": root_id(root), "action": "move", "path": "Game", "parent": "", "name": "NewGame"},
    ]:
        response = client.post("/api/skills/operations", json=operation)
        assert response.status_code == 409
        assert location in response.json()["detail"]
    assert (root / "Game/demo/SKILL.md").exists()


def test_invalid_configuration_blocks_mutation_without_hiding_error(setup):
    root, api, client = setup
    write_skill(root, "demo")
    (api.workspace / "agent").mkdir()
    (api.workspace / "agent/bad.json").write_text("{", encoding="utf-8")
    response = client.post("/api/skills/operations", json={"root_id": root_id(root), "action": "delete", "path": "demo"})
    assert response.status_code == 400
    assert "agent/bad.json" in response.json()["detail"]
    assert (root / "demo").exists()
    inventory = api.list_skills()
    assert inventory["sources"][0]["entries"][0]["path"] == "demo"
    assert "agent/bad.json" in inventory["usage_error"]


def test_links_cannot_escape_root(setup, tmp_path):
    root, api, client = setup
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (root / "link").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Creating symlinks requires OS permissions")
    assert api.list_skills()["sources"][0]["entries"][0]["error"]
    assert client.post("/api/skills/operations", json={"root_id": root_id(root), "action": "delete", "path": "link"}).status_code == 400
    assert outside.exists()


def test_operation_contract_rejects_unknown_or_unstructured_fields(setup):
    root, _, client = setup
    for operation in [{"root_id": root_id(root), "action": "wipe"}, {"root_id": root_id(root), "action": "delete", "path": ["demo"]}, {"root_id": root_id(root), "action": "delete", "path": "demo", "force": True}]:
        assert client.post("/api/skills/operations", json=operation).status_code == 422


def test_reference_guard_respects_path_segments_and_platform_case():
    references = {"Game/demo": ["node-a"], "Gameplay/demo": ["node-b"]}
    assert references_under(references, "Game") == ["node-a"]
    assert references_under(references, "game") == (["node-a"] if os.name == "nt" else [])


def test_multiline_metadata_and_invalid_field_types(setup):
    root, api, _ = setup
    write_skill(root, "folded", description=">\n  多层目录\n  技能说明")
    write_skill(root, "wrong-type", description="[not, a, string]")
    entries = {entry["path"]: entry for entry in api.list_skills()["sources"][0]["entries"]}
    assert "多层目录 技能说明" in entries["folded"]["description"]
    assert entries["wrong-type"]["error"]
