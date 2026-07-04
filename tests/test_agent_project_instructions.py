def test_agent_project_instructions_loads_agents_md_from_cwd(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_project_instructions import build_agent_project_instructions_context
    from src.providers.agent_project_instructions import format_agent_project_instructions_context
    from src.providers.agent_project_instructions import is_agent_project_instructions_text

    (tmp_path / "AGENTS.md").write_text("Use the project formatter.\n", encoding="utf-8")
    agent = SimpleNamespace(_aitools_workspace_root=str(tmp_path), config={})

    context = build_agent_project_instructions_context(
        agent,
        environment_context={"workspace_path": str(tmp_path)},
    )
    text = format_agent_project_instructions_context(context)

    assert context["paths"] == [str(tmp_path / "AGENTS.md")]
    assert text.startswith(f"# AGENTS.md instructions for {tmp_path}")
    assert "<INSTRUCTIONS>\nUse the project formatter.\n</INSTRUCTIONS>" in text
    assert is_agent_project_instructions_text(text)


def test_agent_project_instructions_prefers_override_and_walks_from_project_root(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_project_instructions import build_agent_project_instructions_context

    root = tmp_path / "repo"
    nested = root / "pkg" / "app"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root doc", encoding="utf-8")
    (nested / "AGENTS.md").write_text("nested doc", encoding="utf-8")
    (nested / "AGENTS.override.md").write_text("override doc", encoding="utf-8")
    agent = SimpleNamespace(_aitools_workspace_root=str(nested), config={})

    context = build_agent_project_instructions_context(
        agent,
        environment_context={"workspace_path": str(nested)},
    )

    assert context["paths"] == [str(root / "AGENTS.md"), str(nested / "AGENTS.override.md")]
    assert context["text"] == "root doc\n\noverride doc"


def test_agent_project_instructions_uses_fallback_filenames(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_project_instructions import build_agent_project_instructions_context

    (tmp_path / "PROJECT.md").write_text("fallback doc", encoding="utf-8")
    agent = SimpleNamespace(
        _aitools_workspace_root=str(tmp_path),
        config={"projectDocFallbackFilenames": ["PROJECT.md"]},
    )

    context = build_agent_project_instructions_context(
        agent,
        environment_context={"workspace_path": str(tmp_path)},
    )

    assert context["paths"] == [str(tmp_path / "PROJECT.md")]
    assert context["text"] == "fallback doc"


def test_agent_project_instructions_empty_root_markers_disable_parent_walk(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_project_instructions import build_agent_project_instructions_context

    root = tmp_path / "repo"
    nested = root / "pkg"
    nested.mkdir(parents=True)
    (root / ".git").mkdir()
    (root / "AGENTS.md").write_text("root doc", encoding="utf-8")
    (nested / "AGENTS.md").write_text("nested doc", encoding="utf-8")
    agent = SimpleNamespace(
        _aitools_workspace_root=str(nested),
        config={"projectRootMarkers": []},
    )

    context = build_agent_project_instructions_context(
        agent,
        environment_context={"workspace_path": str(nested)},
    )

    assert context["paths"] == [str(nested / "AGENTS.md")]
    assert context["text"] == "nested doc"


def test_agent_project_instructions_formats_replacement_and_removal_notices(tmp_path):
    from src.providers.agent_project_instructions import PROJECT_INSTRUCTIONS_REMOVAL_NOTICE
    from src.providers.agent_project_instructions import PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE
    from src.providers.agent_project_instructions import format_agent_project_instructions_context
    from src.providers.agent_project_instructions import project_instructions_text_hash
    from src.providers.agent_project_instructions import project_instructions_update_notice

    current = {
        "directory": str(tmp_path),
        "paths": [str(tmp_path / "AGENTS.md")],
        "text": "new instructions",
    }
    previous = {
        "project_instructions": {
            "directory": str(tmp_path),
            "paths": [str(tmp_path / "AGENTS.md")],
            "chars": len("old instructions"),
            "text_hash": project_instructions_text_hash("old instructions"),
        }
    }

    notice = project_instructions_update_notice(previous, current)
    text = format_agent_project_instructions_context(current, notice=notice)

    assert notice == PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE
    assert PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE in text
    assert "new instructions" in text
    assert project_instructions_update_notice(previous, {}) == PROJECT_INSTRUCTIONS_REMOVAL_NOTICE
    removal = format_agent_project_instructions_context({}, notice=PROJECT_INSTRUCTIONS_REMOVAL_NOTICE)
    assert PROJECT_INSTRUCTIONS_REMOVAL_NOTICE in removal
