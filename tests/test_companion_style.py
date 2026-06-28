from types import SimpleNamespace

from src.cli_commands import companion_style


class _FakeKernel32:
    def __init__(self, *, get_console_mode_ok=True, set_console_mode_ok=True):
        self.get_console_mode_ok = get_console_mode_ok
        self.set_console_mode_ok = set_console_mode_ok
        self.mode = 0
        self.set_mode_calls = []

    def GetStdHandle(self, handle_id):
        return handle_id

    def GetConsoleMode(self, _handle, mode_ptr):
        if not self.get_console_mode_ok:
            return 0
        mode_ptr._obj.value = self.mode
        return 1

    def SetConsoleMode(self, handle, mode):
        self.set_mode_calls.append((handle, mode))
        if not self.set_console_mode_ok:
            return 0
        self.mode = mode
        return 1


def _tty_stream():
    return SimpleNamespace(isatty=lambda: True)


def test_color_enabled_enables_windows_virtual_terminal(monkeypatch):
    kernel32 = _FakeKernel32()
    monkeypatch.setattr(companion_style.os, "name", "nt")
    monkeypatch.setattr(companion_style.ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("AITOOLS_COLOR", raising=False)
    companion_style._WINDOWS_VT_CACHE.clear()

    styled = companion_style.style("AITools Companion", companion_style.CYAN, companion_style.BOLD, stream=_tty_stream())

    assert styled == "\x1b[36m\x1b[1mAITools Companion\x1b[0m"
    assert kernel32.set_mode_calls == [
        (companion_style.STD_OUTPUT_HANDLE, companion_style.ENABLE_VIRTUAL_TERMINAL_PROCESSING)
    ]


def test_color_enabled_disables_ansi_when_windows_virtual_terminal_is_unavailable(monkeypatch):
    kernel32 = _FakeKernel32(get_console_mode_ok=False)
    monkeypatch.setattr(companion_style.os, "name", "nt")
    monkeypatch.setattr(companion_style.ctypes, "windll", SimpleNamespace(kernel32=kernel32), raising=False)
    monkeypatch.delenv("NO_COLOR", raising=False)
    monkeypatch.delenv("AITOOLS_COLOR", raising=False)
    companion_style._WINDOWS_VT_CACHE.clear()

    styled = companion_style.style("AITools Companion", companion_style.CYAN, companion_style.BOLD, stream=_tty_stream())

    assert styled == "AITools Companion"
    assert kernel32.set_mode_calls == []
