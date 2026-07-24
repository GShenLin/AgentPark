import os
import types

import pytest
from fastapi import HTTPException

from src.web_backend import runtime_paths
from src.web_backend.core_system_api import SystemApiDomain


def _system_api(monkeypatch, runtime_root):
    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(runtime_root))
    import src.web_backend.core_system_api as core_system_api
    import src.web_backend.system_file_api as system_file_api

    monkeypatch.setattr(core_system_api, "_get_runtime_root", lambda: str(runtime_root))
    monkeypatch.setattr(system_file_api, "_get_runtime_root", lambda: str(runtime_root))
    return SystemApiDomain(object())


def test_list_providers_includes_private_only_for_local_requests(monkeypatch, tmp_path):
    import src.web_backend.core_system_api as core_system_api

    include_private_values = []

    def fake_build_provider_support_list(*, include_private):
        include_private_values.append(include_private)
        return []

    monkeypatch.setattr(
        core_system_api,
        "build_provider_support_list",
        fake_build_provider_support_list,
    )
    api = _system_api(monkeypatch, tmp_path)
    local_request = types.SimpleNamespace(
        client=types.SimpleNamespace(host="127.0.0.1"),
    )
    remote_request = types.SimpleNamespace(
        client=types.SimpleNamespace(host="192.0.2.10"),
    )

    assert api.list_providers(local_request) == {"providers": []}
    assert api.list_providers(remote_request) == {"providers": []}
    assert include_private_values == [True, False]


def test_file_api_resolves_relative_paths_inside_runtime_root(monkeypatch, tmp_path):
    api = _system_api(monkeypatch, tmp_path)

    resolved = api._resolve_file_api_path("nested/demo.txt")

    assert resolved == os.path.abspath(os.path.join(tmp_path, "nested", "demo.txt"))


def test_file_api_allows_runtime_root_absolute_paths(monkeypatch, tmp_path):
    api = _system_api(monkeypatch, tmp_path)
    target = tmp_path / "demo.txt"

    resolved = api._resolve_file_api_path(str(target))

    assert resolved == os.path.abspath(str(target))


def test_file_api_resolves_parent_traversal_without_workspace_boundary(monkeypatch, tmp_path):
    api = _system_api(monkeypatch, tmp_path / "workspace")

    resolved = api._resolve_file_api_path("../outside.txt")

    assert resolved == os.path.abspath(os.path.join(tmp_path, "outside.txt"))


def test_file_api_allows_absolute_paths_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    api = _system_api(monkeypatch, runtime_root)

    resolved = api._resolve_file_api_path(str(outside))

    assert resolved == os.path.abspath(str(outside))


def test_file_api_allows_file_url_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    outside = tmp_path / "outside.txt"
    api = _system_api(monkeypatch, runtime_root)

    resolved = api._resolve_file_api_path(outside.as_uri())

    assert resolved == os.path.abspath(str(outside))


def test_read_file_allows_paths_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("secret", encoding="utf-8")
    api = _system_api(monkeypatch, runtime_root)

    result = api.read_file(str(outside))

    assert result == {"content": "secret", "path": os.path.abspath(str(outside))}


def test_open_file_launches_existing_file_for_local_request(monkeypatch, tmp_path):
    target = tmp_path / "demo.txt"
    target.write_text("hello", encoding="utf-8")
    api = _system_api(monkeypatch, tmp_path)
    launched = []
    monkeypatch.setattr(api, "_launch_local_file", lambda path: launched.append(path))
    request = types.SimpleNamespace(client=types.SimpleNamespace(host="127.0.0.1"))

    result = api.open_file({"path": target.as_uri()}, request)

    expected_path = os.path.abspath(str(target))
    assert result == {"ok": True, "path": expected_path}
    assert launched == [expected_path]


def test_open_file_rejects_remote_request(monkeypatch, tmp_path):
    target = tmp_path / "demo.txt"
    target.write_text("hello", encoding="utf-8")
    api = _system_api(monkeypatch, tmp_path)
    request = types.SimpleNamespace(client=types.SimpleNamespace(host="192.0.2.10"))

    with pytest.raises(HTTPException) as exc_info:
        api.open_file({"path": str(target)}, request)

    assert exc_info.value.status_code == 403


def test_open_file_rejects_missing_file(monkeypatch, tmp_path):
    api = _system_api(monkeypatch, tmp_path)

    with pytest.raises(HTTPException) as exc_info:
        api.open_file({"path": "missing.txt"})

    assert exc_info.value.status_code == 404


def test_list_files_allows_directories_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "demo.txt").write_text("hello", encoding="utf-8")
    api = _system_api(monkeypatch, runtime_root)

    result = api.list_files(str(outside))

    assert result == {
        "files": [{"name": "demo.txt", "path": os.path.abspath(str(outside / "demo.txt")), "type": "file"}],
        "current_path": os.path.abspath(str(outside)),
    }


def test_write_file_creates_files_inside_runtime_root(monkeypatch, tmp_path):
    api = _system_api(monkeypatch, tmp_path)

    result = api.write_file({"path": "nested/demo.txt", "content": "hello"})

    target = tmp_path / "nested" / "demo.txt"
    assert result == {"ok": True, "path": os.path.abspath(str(target))}
    assert target.read_text(encoding="utf-8") == "hello"


def test_write_file_creates_files_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside" / "demo.txt"
    api = _system_api(monkeypatch, runtime_root)

    result = api.write_file({"path": str(outside), "content": "hello outside"})

    assert result == {"ok": True, "path": os.path.abspath(str(outside))}
    assert outside.read_text(encoding="utf-8") == "hello outside"


def test_rename_file_allows_paths_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside.txt"
    renamed = tmp_path / "renamed.txt"
    outside.write_text("move me", encoding="utf-8")
    api = _system_api(monkeypatch, runtime_root)

    result = api.rename_file({"old_path": str(outside), "new_path": str(renamed)})

    assert result == {
        "ok": True,
        "old_path": os.path.abspath(str(outside)),
        "new_path": os.path.abspath(str(renamed)),
    }
    assert not outside.exists()
    assert renamed.read_text(encoding="utf-8") == "move me"


def test_delete_file_allows_paths_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("delete me", encoding="utf-8")
    api = _system_api(monkeypatch, runtime_root)

    result = api.delete_file({"path": str(outside)})

    assert result == {"ok": True, "path": os.path.abspath(str(outside))}
    assert not outside.exists()


def test_select_folder_returns_workspace_relative_selection(monkeypatch, tmp_path):
    selected = tmp_path / "nested"
    selected.mkdir()
    api = _system_api(monkeypatch, tmp_path)

    class FakeTk:
        def withdraw(self):
            return None

        def attributes(self, *args):
            return None

        def destroy(self):
            return None

    fake_filedialog = types.SimpleNamespace(askdirectory=lambda **kwargs: str(selected))
    fake_tk_module = types.SimpleNamespace(Tk=FakeTk, filedialog=fake_filedialog)
    monkeypatch.setitem(__import__("sys").modules, "tkinter", fake_tk_module)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog", fake_filedialog)

    result = api.select_folder({"initial_path": "nested"})

    assert result == {"ok": True, "path": os.path.abspath(str(selected))}


def test_select_folder_allows_paths_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    api = _system_api(monkeypatch, runtime_root)

    class FakeTk:
        def withdraw(self):
            return None

        def attributes(self, *args):
            return None

        def destroy(self):
            return None

    fake_filedialog = types.SimpleNamespace(askdirectory=lambda **kwargs: str(outside))
    fake_tk_module = types.SimpleNamespace(Tk=FakeTk, filedialog=fake_filedialog)
    monkeypatch.setitem(__import__("sys").modules, "tkinter", fake_tk_module)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog", fake_filedialog)

    result = api.select_folder({})

    assert result == {"ok": True, "path": os.path.abspath(str(outside))}


def test_select_folder_allows_initial_path_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    seen = {}
    api = _system_api(monkeypatch, runtime_root)

    class FakeTk:
        def withdraw(self):
            return None

        def attributes(self, *args):
            return None

        def destroy(self):
            return None

    def fake_askdirectory(**kwargs):
        seen.update(kwargs)
        return str(outside)

    fake_filedialog = types.SimpleNamespace(askdirectory=fake_askdirectory)
    fake_tk_module = types.SimpleNamespace(Tk=FakeTk, filedialog=fake_filedialog)
    monkeypatch.setitem(__import__("sys").modules, "tkinter", fake_tk_module)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog", fake_filedialog)

    result = api.select_folder({"initial_path": str(outside)})

    assert seen["initialdir"] == os.path.abspath(str(outside))
    assert result == {"ok": True, "path": os.path.abspath(str(outside))}


def test_select_file_uses_node_directory_as_initial_path(monkeypatch, tmp_path):
    node_dir = tmp_path / "memories" / "Main" / "Worker"
    node_dir.mkdir(parents=True)
    selected = node_dir / "Soul.md"
    selected.write_text("soul", encoding="utf-8")
    seen = {}
    api = _system_api(monkeypatch, tmp_path)

    class FakeTk:
        def withdraw(self):
            return None

        def attributes(self, *args):
            return None

        def destroy(self):
            return None

    def fake_askopenfilename(**kwargs):
        seen.update(kwargs)
        return str(selected)

    fake_filedialog = types.SimpleNamespace(askopenfilename=fake_askopenfilename)
    fake_tk_module = types.SimpleNamespace(Tk=FakeTk, filedialog=fake_filedialog)
    monkeypatch.setitem(__import__("sys").modules, "tkinter", fake_tk_module)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog", fake_filedialog)

    result = api.select_file({"initial_path": "memories/Main/Worker"})

    assert seen["initialdir"] == os.path.abspath(str(node_dir))
    assert result == {"ok": True, "path": os.path.abspath(str(selected))}


def test_select_file_allows_file_outside_runtime_root(monkeypatch, tmp_path):
    runtime_root = tmp_path / "workspace"
    runtime_root.mkdir()
    outside = tmp_path / "outside" / "User.md"
    outside.parent.mkdir()
    outside.write_text("user", encoding="utf-8")
    api = _system_api(monkeypatch, runtime_root)

    class FakeTk:
        def withdraw(self):
            return None

        def attributes(self, *args):
            return None

        def destroy(self):
            return None

    fake_filedialog = types.SimpleNamespace(askopenfilename=lambda **kwargs: str(outside))
    fake_tk_module = types.SimpleNamespace(Tk=FakeTk, filedialog=fake_filedialog)
    monkeypatch.setitem(__import__("sys").modules, "tkinter", fake_tk_module)
    monkeypatch.setitem(__import__("sys").modules, "tkinter.filedialog", fake_filedialog)

    result = api.select_file({})

    assert result == {"ok": True, "path": os.path.abspath(str(outside))}
