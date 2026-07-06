import json


def test_load_default_instructions_matches_model_slug(monkeypatch, tmp_path):
    from src.providers import instructions

    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-a", "instructions": "A instructions"},
                    {"slug": "gpt-b", "instructions": "B instructions"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(instructions, "_models_catalog_path", lambda: str(path))

    assert instructions.load_default_instructions(model="gpt-b") == "B instructions"


def test_resolve_agent_default_instructions_respects_disable_flag():
    from types import SimpleNamespace

    from src.providers.instructions import resolve_agent_default_instructions

    agent = SimpleNamespace(config={"defaultInstructions": False, "defaultInstructionsText": "ignored"})

    assert resolve_agent_default_instructions(agent) == ""


def test_resolve_agent_default_instructions_uses_inline_text():
    from types import SimpleNamespace

    from src.providers.instructions import resolve_agent_default_instructions

    agent = SimpleNamespace(config={"defaultInstructionsText": "Default instructions"})

    assert resolve_agent_default_instructions(agent) == "Default instructions"


def test_resolve_agent_default_instructions_ignores_codex_model_path_keys(monkeypatch, tmp_path):
    from types import SimpleNamespace

    from src.providers import instructions

    default_catalog = tmp_path / "default" / "models.json"
    codex_catalog = tmp_path / "codex" / "models.json"
    default_catalog.parent.mkdir()
    codex_catalog.parent.mkdir()
    default_catalog.write_text(
        json.dumps({"models": [{"slug": "gpt-b", "instructions": "Default catalog"}]}),
        encoding="utf-8",
    )
    codex_catalog.write_text(
        json.dumps({"models": [{"slug": "gpt-b", "instructions": "Codex path catalog"}]}),
        encoding="utf-8",
    )
    monkeypatch.setattr(instructions, "_models_catalog_path", lambda: str(default_catalog))

    agent = SimpleNamespace(
        config={
            "model": "gpt-b",
            "codexModelsPath": str(codex_catalog),
            "codex_models_path": str(codex_catalog),
        }
    )

    assert instructions.resolve_agent_default_instructions(agent) == "Default catalog"
