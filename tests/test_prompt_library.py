def test_prompt_library_uses_workspace_field_directories(monkeypatch, tmp_path):
    import src.web_backend.prompt_library as prompt_library_module
    from src.web_backend.prompt_library import PromptLibrary

    monkeypatch.setattr(prompt_library_module, "get_workspace_root", lambda: str(tmp_path))

    library = PromptLibrary(object())
    saved = library.save_prompt({"kind": "instruction", "filename": "node_instruction", "content": "Use the instruction field."})
    system_saved = library.save_prompt({"kind": "system_prompt", "filename": "node_system", "content": "Use the system prompt field."})

    assert saved == {"ok": True, "filename": "node_instruction.txt"}
    assert system_saved == {"ok": True, "filename": "node_system.txt"}
    assert (tmp_path / "instruction" / "node_instruction.txt").read_text(encoding="utf-8") == "Use the instruction field."
    assert (tmp_path / "prompt" / "node_system.txt").read_text(encoding="utf-8") == "Use the system prompt field."
    assert library.list_prompts("instruction") == {"prompts": ["node_instruction.txt"]}
    assert library.list_prompts("system_prompt") == {"prompts": ["node_system.txt"]}
    assert library.get_prompt("node_instruction", "instruction") == {"content": "Use the instruction field."}
    assert library.get_prompt("node_system", "system_prompt") == {"content": "Use the system prompt field."}


def test_prompt_library_rejects_path_traversal(monkeypatch, tmp_path):
    import pytest
    import src.web_backend.prompt_library as prompt_library_module
    from src.web_backend.prompt_library import PromptLibrary
    from src.web_backend.shared import HTTPException

    monkeypatch.setattr(prompt_library_module, "get_workspace_root", lambda: str(tmp_path))

    library = PromptLibrary(object())
    with pytest.raises(HTTPException):
        library.save_prompt({"kind": "instruction", "filename": "../outside", "content": "nope"})


def test_prompt_library_rejects_unknown_kind(monkeypatch, tmp_path):
    import pytest
    import src.web_backend.prompt_library as prompt_library_module
    from src.web_backend.prompt_library import PromptLibrary
    from src.web_backend.shared import HTTPException

    monkeypatch.setattr(prompt_library_module, "get_workspace_root", lambda: str(tmp_path))

    library = PromptLibrary(object())
    with pytest.raises(HTTPException):
        library.list_prompts("prompt")
