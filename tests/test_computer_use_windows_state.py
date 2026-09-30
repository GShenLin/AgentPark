import sys
from types import SimpleNamespace

import pytest

from src.computer_use.contracts import ComputerUseError
from src.computer_use import windows_state as native


@pytest.fixture
def gui(monkeypatch):
    state = SimpleNamespace(foreground=10, focus=11, style=0, thread=(100, 200), calls=[])
    api = SimpleNamespace(
        GetForegroundWindow=lambda: state.foreground,
        IsIconic=lambda hwnd: False,
        IsWindowVisible=lambda hwnd: True,
        IsWindowEnabled=lambda hwnd: True,
        GetWindowLong=lambda hwnd, index: state.style,
        GetAncestor=lambda hwnd, flag: 10 if hwnd == 11 else hwnd,
        SetForegroundWindow=lambda hwnd: state.calls.append(hwnd),
    )
    monkeypatch.setitem(sys.modules, 'win32gui', api)
    monkeypatch.setitem(sys.modules, 'win32con', SimpleNamespace(SW_RESTORE=9))
    monkeypatch.setitem(sys.modules, 'pywintypes', SimpleNamespace(error=OSError))
    monkeypatch.setitem(sys.modules, 'win32process', SimpleNamespace(
        GetWindowThreadProcessId=lambda hwnd: (100, 200) if hwnd == 10 else state.thread))
    return state, api


def test_active_window_activation_never_resets_child_focus(gui):
    state, _ = gui
    native.activate(10)
    assert state.calls == []


def test_activation_waits_for_cross_thread_foreground_change(gui, monkeypatch):
    state, _ = gui
    def complete_activation(_seconds):
        state.foreground = 20
    monkeypatch.setattr(native.time, 'sleep', complete_activation)
    native.activate(20)
    assert state.calls == [20]


def test_activation_denial_reports_actual_foreground(gui):
    _, api = gui
    def denied(hwnd):
        raise OSError('denied')
    api.SetForegroundWindow = denied
    with pytest.raises(ComputerUseError, match='foreground_id=10'):
        native.activate(20)


def test_popup_pointer_requires_same_gui_thread_not_just_same_process(gui):
    state, _ = gui
    state.style = 0x80000000
    assert native.accepts_pointer(20, 10)
    state.thread = (101, 200)
    assert not native.accepts_pointer(20, 10)
    state.thread = (100, 201)
    assert not native.accepts_pointer(20, 10)
    state.style = 0
    state.thread = (100, 200)
    assert not native.accepts_pointer(20, 10)


def test_keyboard_cannot_use_unchanged_focus_in_another_window(gui, monkeypatch):
    observed = dict(focus_id=11, active_id=10, menu_owner_id=0, in_menu_mode=False)
    monkeypatch.setattr(native, 'input_state', lambda hwnd: observed.copy())
    native.verify_keyboard(10, observed)
    with pytest.raises(ComputerUseError, match='outside the selected window'):
        native.verify_keyboard(20, observed)


def test_keyboard_detects_native_focus_change_even_with_same_uia_root(gui, monkeypatch):
    observed = dict(focus_id=11, active_id=10, menu_owner_id=0, in_menu_mode=False)
    monkeypatch.setattr(native, 'input_state', lambda hwnd: {**observed, 'focus_id': 12})
    with pytest.raises(ComputerUseError, match='Native keyboard focus or menu changed'):
        native.verify_keyboard(10, observed)
