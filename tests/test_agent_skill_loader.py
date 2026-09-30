from pathlib import Path

import pytest

from nodes.agent_skill_loader import (
    SKILL_NAME_LIST,
    SkillLoadError,
    default_skill_root,
    default_skill_roots,
    inject_node_skills,
    list_available_skill_options,
    load_node_skills,
    render_skill_instructions,
    user_skill_root,
)
from src.capabilities.discovery_cache import invalidate_discovery_cache


def _write_skill(root, name, description="Demo skill", body="Use this skill.", version=""):
    skill_dir = root / name
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    version_line = f"version: {version}\n" if version else ""
    skill_path.write_text(
        f"---\nname: {name}\ndescription: {description}\n{version_line}---\n\n{body}\n",
        encoding="utf-8",
    )
    return skill_path


def test_default_skill_root_uses_agents_directory_without_legacy_fallback():
    project_root = Path(__file__).resolve().parents[1]

    assert Path(default_skill_root()) == project_root / ".agents" / "skills"
    assert Path(default_skill_root()) != project_root / "skills"


def test_default_skill_roots_include_project_before_user_directory():
    assert default_skill_roots() == (default_skill_root(), user_skill_root())


def test_default_skill_discovery_and_loading_include_user_root_with_project_precedence(tmp_path, monkeypatch):
    import nodes.agent_skill_loader as skill_loader

    project_root = tmp_path / "project-skills"
    user_root = tmp_path / "user-skills"
    _write_skill(project_root, "project-only", description="Project only")
    project_shared = _write_skill(project_root, "shared", description="Project shared", body="Project instructions.")
    _write_skill(user_root, "user-only", description="User only")
    _write_skill(user_root, "shared", description="User shared", body="User instructions.")
    monkeypatch.setattr(skill_loader, "default_skill_root", lambda: str(project_root))
    monkeypatch.setattr(skill_loader, "user_skill_root", lambda: str(user_root))
    invalidate_discovery_cache("skills", str(project_root))
    invalidate_discovery_cache("skills", str(user_root))

    options = list_available_skill_options()
    by_value = {item["value"]: item for item in options}
    loaded = load_node_skills(["user-only", "shared"], node_id="node-a")

    assert set(by_value) == {"project-only", "shared", "user-only"}
    assert by_value["shared"]["label"] == "shared - Project shared"
    assert loaded[0].description == "User only"
    assert loaded[1].path == str(project_shared)
    assert loaded[1].content.strip() == "Project instructions."


def test_skill_name_list_trims_deduplicates_and_rejects_loose_shapes():
    assert SKILL_NAME_LIST.parse([" demo ", "", "DEMO", "other"]) == ["demo", "DEMO", "other"]
    assert SKILL_NAME_LIST.parse(["browser/control", "browser\\control"]) == ["browser/control"]

    with pytest.raises(SkillLoadError):
        SKILL_NAME_LIST.parse({"name": "demo"})

    with pytest.raises(SkillLoadError):
        SKILL_NAME_LIST.parse(["demo", {"name": "other"}])


def test_load_node_skills_reads_frontmatter_and_renders_bounded_context(tmp_path):
    skill_path = _write_skill(tmp_path, "demo", version="1.2.3")
    refs = tmp_path / "demo" / "references"
    refs.mkdir()
    hidden_tail = "TAIL_CONTENT_THAT_MUST_NOT_BE_IN_PROMPT"
    (refs / "guide.md").write_text(
        "# Guide\n\nReference body summary is allowed.\n" + ("x" * 400) + hidden_tail + "\n",
        encoding="utf-8",
    )

    skills = load_node_skills(["demo", "demo"], node_id="node-a", skill_root=str(tmp_path))

    assert len(skills) == 1
    assert skills[0].name == "demo"
    assert skills[0].description == "Demo skill"
    assert skills[0].version == "1.2.3"
    assert skills[0].path == str(skill_path)
    assert len(skills[0].resources) == 1
    assert skills[0].resources[0].path == "references/guide.md"

    rendered = render_skill_instructions(skills)
    assert rendered.startswith("<skills_instructions>")
    assert "<name>demo</name>" in rendered
    assert "<version>1.2.3</version>" in rendered
    assert "<path>" in rendered
    assert "Use this skill." in rendered
    assert "<resources>" in rendered
    assert "<path>references/guide.md</path>" in rendered
    assert "Reference body summary is allowed." in rendered
    assert hidden_tail not in rendered
    assert rendered.endswith("</skills_instructions>")


def test_load_node_skills_supports_multiline_yaml_description(tmp_path):
    skill_dir = tmp_path / "browser-skill"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: browser-skill\n"
        "description: |\n"
        "  Automate the user's Chromium browser: read pages, fill forms,\n"
        "  scrape data, operate tabs, test a UI, or debug a website.\n"
        "---\n\n"
        "Use the browser skill.\n",
        encoding="utf-8",
    )

    option = list_available_skill_options(str(tmp_path))[0]
    skill = load_node_skills(["browser-skill"], node_id="node-a", skill_root=str(tmp_path))[0]

    assert option["value"] == "browser-skill"
    assert option["label"].startswith("browser-skill - Automate the user's Chromium browser")
    assert skill.description == (
        "Automate the user's Chromium browser: read pages, fill forms,\n"
        "scrape data, operate tabs, test a UI, or debug a website."
    )
    assert skill.path == str(skill_path)


def test_load_node_skills_reads_version_from_nested_metadata(tmp_path):
    skill_dir = tmp_path / "nested-version"
    skill_dir.mkdir()
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        "---\n"
        "name: nested-version\n"
        "description: Skill with nested metadata.\n"
        "metadata:\n"
        "  version: 1.2.3\n"
        "---\n\n"
        "Use the nested-version skill.\n",
        encoding="utf-8",
    )

    option = list_available_skill_options(str(tmp_path))[0]
    skill = load_node_skills(["nested-version"], node_id="node-a", skill_root=str(tmp_path))[0]

    assert option["version"] == "1.2.3"
    assert skill.version == "1.2.3"


def test_load_node_skills_reads_agent_yaml_mcp_dependencies(tmp_path):
    _write_skill(tmp_path, "openai-docs")
    agents_dir = tmp_path / "openai-docs" / "agents"
    agents_dir.mkdir()
    (agents_dir / "openai.yaml").write_text(
        "\n".join(
            [
                "dependencies:",
                "  tools:",
                "    - type: mcp",
                "      value: openaiDeveloperDocs",
                "      description: OpenAI Developer Docs MCP server",
                "      transport: streamable-http",
                "      url: https://developers.openai.com/mcp",
            ]
        ),
        encoding="utf-8",
    )

    skills = load_node_skills(["openai-docs"], node_id="node-a", skill_root=str(tmp_path))

    assert skills[0].mcp_servers == ("openaiDeveloperDocs",)
    assert skills[0].mcp_server_configs == {
        "openaiDeveloperDocs": {
            "label": "OpenAI Developer Docs MCP server",
            "transport": "streamable-http",
            "url": "https://developers.openai.com/mcp",
        }
    }


def test_load_node_skills_reads_agent_yaml_local_tool_dependencies(tmp_path):
    _write_skill(tmp_path, "computer-use")
    agents_dir = tmp_path / "computer-use" / "agents"
    agents_dir.mkdir()
    (agents_dir / "agentpark.yaml").write_text(
        "\n".join([
            "dependencies:",
            "  tools:",
            "    - type: tool",
            "      value: computer_use_tools",
            "      description: Windows UI tools",
        ]),
        encoding="utf-8",
    )

    skill = load_node_skills(["computer-use"], node_id="node-a", skill_root=str(tmp_path))[0]

    assert skill.tools == ("computer_use_tools",)
    assert skill.mcp_servers == ()
    assert skill.resources == ()


def test_load_node_skills_accepts_relative_path_inside_skill_root(tmp_path):
    skill_path = _write_skill(tmp_path, "browser/control", description="Nested skill")

    skills = load_node_skills(["browser/control"], node_id="node-a", skill_root=str(tmp_path))

    assert len(skills) == 1
    assert skills[0].name == "browser/control"
    assert skills[0].description == "Nested skill"
    assert skills[0].path == str(skill_path)


def test_list_available_skill_options_lists_only_skill_directories(tmp_path):
    _write_skill(tmp_path, "demo", description="Demo skill", version="2.0.0")
    _write_skill(tmp_path, "nested/tool", description="Nested skill")
    (tmp_path / "not_a_skill").mkdir()

    options = list_available_skill_options(str(tmp_path))

    assert [item["value"] for item in options] == ["demo", "nested/tool"]
    assert options[0]["label"] == "demo - Demo skill"
    assert options[0]["version"] == "2.0.0"
    assert options[1]["label"] == "nested/tool - Nested skill"
    assert "version" not in options[1]


def test_skill_option_discovery_cache_refreshes_on_explicit_invalidation(tmp_path):
    skill_path = _write_skill(tmp_path, "demo", description="First")
    invalidate_discovery_cache("skills", str(tmp_path))

    first = list_available_skill_options(str(tmp_path))
    skill_path.write_text(
        "---\nname: demo\ndescription: Second\n---\n\nUse this skill.\n",
        encoding="utf-8",
    )
    cached = list_available_skill_options(str(tmp_path))
    invalidate_discovery_cache("skills", str(tmp_path))
    refreshed = list_available_skill_options(str(tmp_path))

    assert first == [{"value": "demo", "label": "demo - First"}]
    assert cached == first
    assert refreshed == [{"value": "demo", "label": "demo - Second"}]


def test_load_node_skills_reads_latest_file_content_without_shared_cache(tmp_path):
    skill_path = _write_skill(tmp_path, "demo", body="First version.")

    first = render_skill_instructions(load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path)))
    skill_path.write_text(
        "---\nname: demo\ndescription: Demo skill\n---\n\nSecond version.\n",
        encoding="utf-8",
    )
    second = render_skill_instructions(load_node_skills(["demo"], node_id="node-a", skill_root=str(tmp_path)))

    assert "First version." in first
    assert "Second version." in second
    assert "First version." not in second


def test_missing_skill_reports_node_skill_and_path(tmp_path):
    with pytest.raises(SkillLoadError) as exc:
        load_node_skills(["missing"], node_id="node-a", skill_root=str(tmp_path))

    message = str(exc.value)
    assert "node node-a" in message
    assert "skill missing" in message
    assert "SKILL.md does not exist" in message


def test_skill_name_cannot_escape_skill_root(tmp_path):
    with pytest.raises(SkillLoadError) as exc:
        load_node_skills(["../config"], node_id="node-a", skill_root=str(tmp_path))

    assert "invalid skill path" in str(exc.value)


def test_invalid_frontmatter_is_not_silently_ignored(tmp_path):
    skill_dir = tmp_path / "bad"
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text("No metadata\n", encoding="utf-8")

    with pytest.raises(SkillLoadError) as exc:
        load_node_skills(["bad"], node_id="node-a", skill_root=str(tmp_path))

    assert "missing YAML frontmatter" in str(exc.value)


def test_inject_node_skills_adds_non_persistent_system_context(tmp_path):
    _write_skill(tmp_path, "demo")

    class Agent:
        def __init__(self):
            self.messages = []

        def Message(self, role, content, persist=True, **kwargs):
            self.messages.append({"role": role, "content": content, "persist": persist, **kwargs})

    agent = Agent()
    inject_node_skills(agent, ["demo"], node_id="node-a", skill_root=str(tmp_path))

    assert len(agent.messages) == 1
    assert agent.messages[0]["role"] == "system"
    assert agent.messages[0]["persist"] is False
    assert "<skills_instructions>" in agent.messages[0]["content"]


def test_inject_node_skills_can_use_developer_context_role(tmp_path):
    _write_skill(tmp_path, "demo", "Demo skill", "Use the demo skill.")

    class Agent:
        def __init__(self):
            self.messages = []

        def Message(self, role, content, persist=True):
            self.messages.append({"role": role, "content": content, "persist": persist})

    agent = Agent()
    inject_node_skills(agent, ["demo"], node_id="node-a", skill_root=str(tmp_path), role="developer")

    assert agent.messages[0]["role"] == "developer"
    assert agent.messages[0]["persist"] is False
    assert "<skills_instructions>" in agent.messages[0]["content"]
