import json
from pathlib import Path

import pytest

import src.web_backend.input_bundle_library as input_bundle_module
from src.web_backend.input_bundle_library import InputBundleLibrary
from src.web_backend.shared import HTTPException


def test_input_bundle_library_round_trips_text_and_attachments(monkeypatch, tmp_path):
    monkeypatch.setattr(input_bundle_module, "get_workspace_root", lambda: str(tmp_path))
    image = tmp_path / "source image.png"
    document = tmp_path / "notes.txt"
    image.write_bytes(b"png-data")
    document.write_text("attachment text", encoding="utf-8")

    library = InputBundleLibrary(object())
    saved = library.save_input_bundle(
        {
            "name": "sample-input",
            "text": "Describe both files.",
            "attachments": [
                {"name": "source image.png", "path": str(image), "kind": "image", "mime": "image/png"},
                {"name": "notes.txt", "path": str(document)},
            ],
        }
    )

    assert saved == {"ok": True, "name": "sample-input"}
    assert library.list_input_bundles() == {"bundles": ["sample-input"]}
    loaded = library.get_input_bundle("sample-input")
    assert loaded["text"] == "Describe both files."
    assert [item["name"] for item in loaded["attachments"]] == ["source image.png", "notes.txt"]
    assert Path(loaded["attachments"][0]["path"]).read_bytes() == b"png-data"
    assert Path(loaded["attachments"][1]["path"]).read_text(encoding="utf-8") == "attachment text"
    manifest = json.loads((tmp_path / "input" / "sample-input" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["version"] == 1
    assert manifest["text_file"] == "text.txt"
    assert len(manifest["attachments"]) == 2


def test_input_bundle_library_replaces_existing_bundle_inside_repository_lock(monkeypatch, tmp_path):
    monkeypatch.setattr(input_bundle_module, "get_workspace_root", lambda: str(tmp_path))
    lock_paths = []
    real_lock = input_bundle_module.run_with_interprocess_lock

    def capture_lock(lock_path, operation):
        lock_paths.append(Path(lock_path))
        return real_lock(lock_path, operation)

    monkeypatch.setattr(input_bundle_module, "run_with_interprocess_lock", capture_lock)
    first_attachment = tmp_path / "first.txt"
    second_attachment = tmp_path / "second.txt"
    first_attachment.write_text("first", encoding="utf-8")
    second_attachment.write_text("second", encoding="utf-8")
    library = InputBundleLibrary(object())

    library.save_input_bundle(
        {"name": "replace-me", "text": "old", "attachments": [{"path": str(first_attachment)}]}
    )
    library.save_input_bundle(
        {"name": "replace-me", "text": "new", "attachments": [{"path": str(second_attachment)}]}
    )

    loaded = library.get_input_bundle("replace-me")
    assert loaded["text"] == "new"
    assert [item["name"] for item in loaded["attachments"]] == ["second.txt"]
    assert lock_paths == [
        tmp_path / "input" / ".replace-me.lock",
        tmp_path / "input" / ".replace-me.lock",
    ]


def test_input_bundle_library_rejects_invalid_names_and_missing_files(monkeypatch, tmp_path):
    monkeypatch.setattr(input_bundle_module, "get_workspace_root", lambda: str(tmp_path))
    library = InputBundleLibrary(object())

    with pytest.raises(HTTPException):
        library.save_input_bundle({"name": "../outside", "text": "nope", "attachments": []})
    with pytest.raises(HTTPException):
        library.save_input_bundle(
            {"name": "missing", "text": "has attachment", "attachments": [{"path": str(tmp_path / "missing.png")}]}
        )


def test_agent_domain_imports_input_bundle_service():
    from src.web_backend.agent_domain import AgentDomain

    assert AgentDomain.__name__ == "AgentDomain"
