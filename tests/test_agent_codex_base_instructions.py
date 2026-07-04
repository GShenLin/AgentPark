import json


def test_load_codex_base_instructions_matches_model_slug(tmp_path):
    from src.providers.agent_codex_base_instructions import load_codex_base_instructions

    path = tmp_path / "models.json"
    path.write_text(
        json.dumps(
            {
                "models": [
                    {"slug": "gpt-a", "base_instructions": "A instructions"},
                    {"slug": "gpt-b", "base_instructions": "B instructions"},
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert load_codex_base_instructions(model="gpt-b", models_path=str(path)) == "B instructions"


def test_resolve_agent_codex_base_instructions_respects_disable_flag(tmp_path):
    from types import SimpleNamespace

    from src.providers.agent_codex_base_instructions import resolve_agent_codex_base_instructions

    agent = SimpleNamespace(config={"codexBaseInstructions": False, "codexBaseInstructionsText": "ignored"})

    assert resolve_agent_codex_base_instructions(agent) == ""


def test_resolve_agent_codex_base_instructions_keeps_explicit_prompt():
    from types import SimpleNamespace

    from src.providers.agent_codex_base_instructions import resolve_agent_codex_base_instructions

    agent = SimpleNamespace(config={"codexBaseInstructionsText": "Codex base"})

    assert resolve_agent_codex_base_instructions(agent, explicit_system_prompt="Node prompt") == "Node prompt"
