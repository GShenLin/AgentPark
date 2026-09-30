import pytest

from src.computer_use.contracts import ComputerUseError
from src.computer_use.windows_backend import WindowsBackend


CURRENT_WINDOW = {
    'id': 264198,
    'app': 'process:C:\\UnrealEditor.exe',
    'pid': 23024,
    'process_started': '2026-09-20T06:40:40.558000+00:00',
    'title': 'XYJ - Unreal Editor',
}


def backend_with_current_window():
    backend = object.__new__(WindowsBackend)
    backend._window = lambda _hwnd: CURRENT_WINDOW.copy()
    return backend


@pytest.mark.parametrize('process_started', [
    '2026-09-20T06:40:40.558+00:00',
    '2026-09-20T06:40:40.558000+00:00',
    '2026-09-20T14:40:40.558+08:00',
])
def test_resolve_compares_process_start_as_an_instant(process_started):
    supplied = {**CURRENT_WINDOW, 'process_started': process_started}

    assert backend_with_current_window().resolve(supplied) == CURRENT_WINDOW


@pytest.mark.parametrize('process_started', [None, '', 'not-a-timestamp', '2026-09-20T06:40:40.558'])
def test_resolve_rejects_invalid_process_start_contract(process_started):
    supplied = {**CURRENT_WINDOW, 'process_started': process_started}

    with pytest.raises(ComputerUseError, match='window.process_started must be an ISO-8601 timestamp'):
        backend_with_current_window().resolve(supplied)


def test_resolve_reports_process_start_mismatch_explicitly():
    supplied = {**CURRENT_WINDOW, 'process_started': '2026-09-20T06:40:41.558+00:00'}

    with pytest.raises(ComputerUseError, match='field process_started does not match'):
        backend_with_current_window().resolve(supplied)


def test_resolve_reports_the_mismatched_identity_field():
    supplied = {**CURRENT_WINDOW, 'pid': CURRENT_WINDOW['pid'] + 1}

    with pytest.raises(ComputerUseError, match='field pid does not match'):
        backend_with_current_window().resolve(supplied)


def test_window_discovery_includes_visible_untitled_popups(monkeypatch):
    import sys
    from types import SimpleNamespace
    from functions.computer_use_tools import _WINDOW
    from jsonschema import validate
    monkeypatch.setitem(sys.modules, 'win32gui', SimpleNamespace(
        EnumWindows=lambda callback, arg: [callback(hwnd, arg) for hwnd in (10, 20, 30)],
        IsWindowVisible=lambda hwnd: hwnd != 30))
    monkeypatch.setitem(sys.modules, 'pywintypes', SimpleNamespace(error=OSError))
    backend = object.__new__(WindowsBackend)
    backend._window = lambda hwnd: {**CURRENT_WINDOW, 'id': hwnd,
                                  'title': 'Editor' if hwnd == 10 else '',
                                  'class_name': 'Popup', 'owner_id': 10, 'thread_id': 123,
                                  'is_foreground': hwnd == 10, 'enabled': True,
                                  'no_activate': hwnd == 20, 'is_tool_window': hwnd == 20}
    windows = backend.list_windows()
    assert [w['id'] for w in windows] == [10, 20]
    assert windows[1]['title'] == ''
    for window in windows:
        validate(window, _WINDOW)
