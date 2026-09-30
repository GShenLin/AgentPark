import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from nodes import agent_skill_loader as loader
from src.skills import roots
from src.skills.management import SkillManager
from src.web_backend.skills_api import SkillsApi, SkillRootOperation


def write_skill(root, reference, text):
    path = root / reference / "SKILL.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nname: {reference}\ndescription: {text}\n---\n{text}", encoding="utf-8")
    return path


@pytest.fixture
def env(tmp_path, monkeypatch):
    workspace = tmp_path / "workspace"
    project = workspace / ".agents/skills"
    user = tmp_path / "user/.agents/skills"
    custom = tmp_path / "custom"
    for path in (project, user, custom):
        path.mkdir(parents=True)
    monkeypatch.setattr(roots, "get_workspace_root", lambda: str(workspace))
    monkeypatch.setattr(loader, "default_skill_root", lambda: str(project))
    monkeypatch.setattr(loader, "user_skill_root", lambda: str(user))
    api = SkillsApi(project, workspace, workspace / "memories", user)
    app = FastAPI()
    app.get("/api/skills")(api.list_skills)
    app.get("/api/skills/detail")(api.detail)
    app.post("/api/skills/roots")(api.configure_roots)
    app.post("/api/skills/operations")(api.operate)
    return api, project, user, custom, TestClient(app)


def test_default_catalog_includes_both_roots_with_separate_identifiers(env):
    api, project, user, _, client = env
    write_skill(project, "same", "Project version")
    write_skill(user, "same", "User version")
    write_skill(user, "user-only", "User only")
    catalog = client.get("/api/skills").json()
    assert len(catalog["sources"]) == 2
    project_entry = catalog["sources"][0]["entries"][0]
    user_entry = catalog["sources"][1]["entries"][0]
    assert project_entry["root_id"] != user_entry["root_id"]
    assert user_entry["shadowed_by"] == "当前项目"
    for entry, expected in [(project_entry, "Project version"), (user_entry, "User version")]:
        detail = client.get("/api/skills/detail", params={"root_id": entry["root_id"], "path": "same"}).json()
        assert expected in detail["content"]
    assert loader.load_node_skills(["same"])[0].description == "Project version"


def test_added_roots_persist_and_are_used_by_real_runtime(env):
    api, _, _, custom, client = env
    write_skill(custom, "Game/Design/demo", "Custom skill")
    response = client.post("/api/skills/roots", json={"action": "add", "path": str(custom)})
    assert response.status_code == 200
    assert str(custom) in loader.default_skill_roots()
    assert loader.list_available_skill_options()[0]["value"] == "Game/Design/demo"
    assert loader.load_node_skills(["Game/Design/demo"])[0].description == "Custom skill"
    reloaded = roots.SkillRootStore(api.workspace, api.roots.project, api.roots.user)
    assert reloaded.sources()[-1]["path"] == str(custom)
    source = api.list_skills()["sources"][-1]
    assert source["entries"][-1]["description"] == "Custom skill"
    response = client.post("/api/skills/roots", json={"action": "remove", "root_id": source["id"]})
    assert response.status_code == 200
    assert (custom / "Game/Design/demo/SKILL.md").exists()
    assert "Game/Design/demo" not in {item["value"] for item in loader.list_available_skill_options()}


def test_custom_root_order_and_project_precedence_match_catalog(env):
    api, project, user, custom, _ = env
    write_skill(project, "same", "Project")
    write_skill(user, "same", "User")
    write_skill(custom, "same", "Custom")
    api.configure_roots(SkillRootOperation(action="add", path=str(custom)))
    options = loader.list_available_skill_options()
    assert len(options) == 1 and "Project" in options[0]["label"]
    assert loader.load_node_skills(["same"])[0].description == "Project"
    assert api.list_skills()["sources"][-1]["entries"][0]["shadowed_by"] == "当前项目"


def test_path_configuration_rejects_invalid_duplicate_and_nested_roots(env):
    api, project, user, custom, client = env
    bundle = write_skill(custom, "demo", "Demo").parent
    for path in ("relative/path", str(custom / "missing"), str(project), str(project.parent), str(bundle), str(user)):
        assert client.post("/api/skills/roots", json={"action": "add", "path": path}).status_code == 400
    for source in api.roots.sources():
        assert client.post("/api/skills/roots", json={"action": "remove", "root_id": source["id"]}).status_code == 400


def test_missing_custom_directory_is_reported_without_losing_other_sources(env):
    api, project, _, custom, _ = env
    write_skill(project, "demo", "Project")
    api.configure_roots(SkillRootOperation(action="add", path=str(custom)))
    custom.rmdir()
    sources = api.list_skills()["sources"]
    assert not sources[-1]["exists"]
    assert sources[-1]["entries"] == []
    assert sources[0]["entries"][0]["name"] == "demo"


def test_in_use_custom_root_cannot_be_unloaded(env):
    api, _, _, custom, client = env
    write_skill(custom, "demo", "Demo")
    api.configure_roots(SkillRootOperation(action="add", path=str(custom)))
    profile = api.workspace / "agent/demo.json"
    profile.parent.mkdir()
    profile.write_text(json.dumps({"skills": ["demo"]}), encoding="utf-8")
    identifier = api.roots.sources()[-1]["id"]
    assert client.post("/api/skills/roots", json={"action": "remove", "root_id": identifier}).status_code == 409


def test_unknown_source_cannot_be_used_to_access_arbitrary_directory(env):
    _, _, _, custom, client = env
    assert client.get("/api/skills/detail", params={"root_id": str(custom), "path": "demo"}).status_code == 404
    assert client.post("/api/skills/operations", json={"action": "delete", "path": "demo"}).status_code == 422


def test_neighboring_roots_have_independent_trash(env):
    _, _, _, custom, _ = env
    other = custom.parent / "other"
    write_skill(custom, "demo", "Custom")
    write_skill(other, "demo", "Other")
    first, second = SkillManager(custom), SkillManager(other)
    first.delete("demo")
    second.delete("demo")
    assert first.trash != second.trash
    first.restore(first.deleted()[0]["id"])
    assert (custom / "demo/SKILL.md").exists()
    assert not (other / "demo").exists()
