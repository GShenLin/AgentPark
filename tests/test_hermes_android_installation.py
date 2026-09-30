import pytest

from src.harness import hermes_python


@pytest.mark.parametrize("existing", [False, True])
def test_incompatible_android_python_stops_before_install(tmp_path, monkeypatch, existing):
    monkeypatch.setattr(hermes_python.shutil, "which", lambda name: None)
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nrequires-python=">=3.11,<3.14"\n')
    python = tmp_path / "venv" / "bin" / "python"
    if existing:
        python.parent.mkdir(parents=True)
        python.touch()
    calls = []
    def run(argv, **kwargs):
        calls.append(argv)
        return "3.14.6"
    monkeypatch.setattr(hermes_python, "run_process", run)
    with pytest.raises(ValueError, match="requires Python >=3.11,<3.14.*3.14.6"):
        hermes_python.install_android(python, source, [])
    assert len(calls) == 1
    assert calls[0][0] == (str(python) if existing else hermes_python.sys.executable)
    assert not any("pip" in arg or "uv" == arg for arg in calls[0])


@pytest.mark.parametrize("existing", [False, True])
def test_android_installs_in_original_venv_with_release_constraints(tmp_path, monkeypatch, existing):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nrequires-python=">=3.11,<3.14"\n')
    constraints = source / "constraints-termux.txt"
    constraints.touch()
    prepare = source / "scripts" / "install_psutil_android.py"
    prepare.parent.mkdir()
    prepare.touch()
    python = tmp_path / "venv" / "bin" / "python"
    if existing:
        python.parent.mkdir(parents=True)
        python.touch()
    monkeypatch.setattr(hermes_python.sys, "platform", "android")
    monkeypatch.setenv("PYTHONPATH", "/unrelated")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return "3.13.7" if "-c" in argv else "ok"
    monkeypatch.setattr(hermes_python, "run_process", run)
    hermes_python.install_android(python, source, [])
    assert len(calls) == (4 if existing else 5)
    if not existing:
        assert calls[1][0] == [hermes_python.sys.executable, "-m", "venv", str(python.parent.parent)]
    assert calls[-2][0][:2] == [str(python), str(prepare)]
    assert calls[-1][0] == [str(python), "-m", "pip", "install", "-e", str(source), "-c", str(constraints)]
    assert "PYTHONPATH" not in calls[-1][1]["env"]


def test_android_dependency_failure_is_not_hidden(tmp_path, monkeypatch):
    source = tmp_path / "source"
    source.mkdir()
    (source / "pyproject.toml").write_text('[project]\nrequires-python=">=3.11,<3.14"\n')
    (source / "constraints-termux.txt").touch()
    python = tmp_path / "venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.touch()
    def run(argv, **kwargs):
        if argv[1] == "-c":
            return "3.13.7"
        raise RuntimeError("native dependency build failed")
    monkeypatch.setattr(hermes_python, "run_process", run)
    with pytest.raises(RuntimeError, match="native dependency build failed"):
        hermes_python.install_android(python, source, [])


def test_selects_installed_compatible_python_for_new_environment(tmp_path, monkeypatch):
    monkeypatch.setattr(hermes_python.shutil, "which", lambda name: "/native/python3.13" if name == "python3.13" else None)
    monkeypatch.setattr(hermes_python, "run_process", lambda argv, **kwargs:
                        "3.13.13" if argv[0] == "/native/python3.13" else "3.14.6")
    assert hermes_python.compatible_python(tmp_path / "missing", tmp_path, ">=3.11,<3.14") == "/native/python3.13"


def test_existing_environment_is_never_silently_replaced(tmp_path, monkeypatch):
    python = tmp_path / "python"
    python.touch()
    monkeypatch.setattr(hermes_python.shutil, "which", lambda name: pytest.fail("Must preserve existing interpreter"))
    monkeypatch.setattr(hermes_python, "run_process", lambda *args, **kwargs: "3.14.6")
    with pytest.raises(ValueError, match="must be recreated"):
        hermes_python.compatible_python(python, tmp_path, ">=3.11,<3.14")
