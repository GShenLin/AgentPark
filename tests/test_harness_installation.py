from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from fastapi import HTTPException
import pytest
from starlette.requests import Request

from src.harness import install_manager as manager
from src.harness.registry import descriptor
from src.web_backend.harness_api import HarnessApiDomain, HarnessOperation


def package(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    root = manager.install_root("pi") / "node_modules" / descriptor("pi").package
    root.mkdir(parents=True)
    (root / "cli.js").write_text("", encoding="utf-8")
    (root / "package.json").write_text(json.dumps({"name": descriptor("pi").package, "bin": {"pi": "cli.js"}}))
    return root


def test_installation_uses_declared_bin_and_rejects_escape(tmp_path, monkeypatch):
    root = package(tmp_path, monkeypatch)
    monkeypatch.setattr(manager.shutil, "which", lambda name: "/node" if name == "node" else None)
    assert manager.managed_argv("pi") == ["/node", str((root / "cli.js").resolve())]
    (root / "package.json").write_text(json.dumps({"name": descriptor("pi").package, "bin": {"pi": "../../other.js"}}))
    with pytest.raises(ValueError, match="Invalid Harness executable"):
        manager.managed_argv("pi")


def test_external_installation_is_not_uninstalled(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    with pytest.raises(ValueError, match="Only installations owned"):
        manager.mutate_installation("pi", "uninstall")
    assert "pi" not in manager._MUTATING


def test_active_node_blocks_uninstall_and_releases_after_failure():
    with pytest.raises(RuntimeError, match="turn failed"):
        with manager.runtime_lease("pi"):
            with pytest.raises(RuntimeError, match="busy"):
                manager.mutate_installation("pi", "uninstall")
            raise RuntimeError("turn failed")
    assert manager._ACTIVE["pi"] == 0


def test_mutation_uses_fixed_package_and_workspace_prefix(tmp_path, monkeypatch):
    monkeypatch.setattr(manager, "get_workspace_root", lambda: str(tmp_path))
    monkeypatch.setattr(manager, "npm_argv", lambda: ["node", "npm-cli.js"])
    called = []
    monkeypatch.setattr(manager, "run_process", lambda argv, **kwargs: called.append(argv) or "installed")
    monkeypatch.setattr(manager, "check_installation", lambda key: {"status": "ready"})
    manager.mutate_installation("pi", "install")
    assert called[0][-1] == "@earendil-works/pi-coding-agent@latest"
    assert "--engine-strict" in called[0]
    assert str(manager.install_root("pi")) in called[0]
    with pytest.raises(ValueError, match="Unknown Harness"):
        manager.mutate_installation("../../bad", "install")


def test_management_requires_owner_and_payload_is_closed():
    domain = HarnessApiDomain(SimpleNamespace())
    remote = Request({"type": "http", "client": ("203.0.113.8", 80), "headers": []})
    with pytest.raises(HTTPException) as error:
        domain.list_harnesses(remote)
    assert error.value.status_code == 403
    with pytest.raises(ValueError):
        HarnessOperation(action="install", command="arbitrary command")


def test_shared_runtime_locks_allow_concurrency_and_block_mutation(tmp_path):
    from src.harness.file_lock import file_lease
    path = tmp_path / "runtime.lock"
    with file_lease(path, exclusive=False):
        with file_lease(path, exclusive=False):
            with pytest.raises(RuntimeError, match="busy"):
                with file_lease(path, exclusive=True):
                    pytest.fail("exclusive lock must not succeed")
    with file_lease(path, exclusive=True):
        with pytest.raises(RuntimeError, match="busy"):
            with file_lease(path, exclusive=False):
                pytest.fail("shared lock must not succeed")
