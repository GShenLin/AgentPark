"""Native window activation and input-queue state, independent of UI Automation."""
import ctypes
from ctypes import wintypes
import time

from .contracts import ComputerUseError


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [('cbSize', wintypes.DWORD), ('flags', wintypes.DWORD),
                ('hwndActive', wintypes.HWND), ('hwndFocus', wintypes.HWND),
                ('hwndCapture', wintypes.HWND), ('hwndMenuOwner', wintypes.HWND),
                ('hwndMoveSize', wintypes.HWND), ('hwndCaret', wintypes.HWND),
                ('rcCaret', wintypes.RECT)]


def window_details(hwnd):
    import win32gui
    import win32process
    return {
        'class_name': win32gui.GetClassName(hwnd),
        'owner_id': win32gui.GetWindow(hwnd, 4),
        'thread_id': win32process.GetWindowThreadProcessId(hwnd)[0],
        'is_foreground': win32gui.GetForegroundWindow() == hwnd,
        'enabled': bool(win32gui.IsWindowEnabled(hwnd)),
        'no_activate': bool(win32gui.GetWindowLong(hwnd, -20) & 0x08000000),
        'is_tool_window': bool(win32gui.GetWindowLong(hwnd, -20) & 0x80),
    }


def input_state(hwnd):
    import win32gui
    import win32process
    thread_id = win32process.GetWindowThreadProcessId(hwnd)[0]
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.GetGUIThreadInfo.argtypes = [wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    api.GetGUIThreadInfo.restype = wintypes.BOOL
    info = GUITHREADINFO(cbSize=ctypes.sizeof(GUITHREADINFO))
    if not api.GetGUIThreadInfo(thread_id, ctypes.byref(info)):
        raise ComputerUseError(f'Cannot inspect target input queue: {ctypes.WinError(ctypes.get_last_error())}')
    return {'foreground_id': win32gui.GetForegroundWindow(),
            'active_id': info.hwndActive or 0, 'focus_id': info.hwndFocus or 0,
            'capture_id': info.hwndCapture or 0, 'menu_owner_id': info.hwndMenuOwner or 0,
            'in_menu_mode': bool(info.flags & 0x1C)}


def accepts_pointer(hwnd, foreground):
    """A separately observed popup can take clicks while its GUI thread stays active."""
    import win32gui
    import win32process
    if not foreground or not win32gui.IsWindowVisible(hwnd) or not win32gui.IsWindowEnabled(hwnd):
        return False
    if foreground == hwnd:
        return True
    return (bool(win32gui.GetWindowLong(hwnd, -16) & 0x80000000) and
            win32process.GetWindowThreadProcessId(hwnd) ==
            win32process.GetWindowThreadProcessId(foreground))


def activate(hwnd):
    import win32con
    import win32gui
    import pywintypes
    if win32gui.GetForegroundWindow() == hwnd and not win32gui.IsIconic(hwnd):
        return  # Preserve the focused child and open menu of an already active window.
    if not win32gui.IsWindowEnabled(hwnd):
        raise ComputerUseError('Target is disabled, possibly by a modal window; call list_windows and observe that window.')
    if win32gui.GetWindowLong(hwnd, -20) & 0x08000000:
        raise ComputerUseError('Target is a non-activating popup; observe and click it with its application in the foreground.')
    if win32gui.IsIconic(hwnd):
        win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
    try:
        win32gui.SetForegroundWindow(hwnd)
    except pywintypes.error as exc:
        raise ComputerUseError(
            f'Windows denied activation of {hwnd}; foreground_id={win32gui.GetForegroundWindow()}. '
            'Call list_windows to inspect the foreground window; user activation may be required.') from exc
    # Activation crosses input queues and is asynchronous. Wait for the requested
    # state, without resending activation or changing child keyboard focus.
    deadline = time.monotonic() + 1
    while win32gui.GetForegroundWindow() != hwnd:
        if time.monotonic() >= deadline:
            raise ComputerUseError(
                f'Activation did not complete for {hwnd}; foreground_id={win32gui.GetForegroundWindow()}. '
                'Call list_windows and observe the foreground window.')
        time.sleep(0.01)


def verify_keyboard(hwnd, observed):
    import win32gui
    current = input_state(hwnd)
    if observed is None or any(current[key] != observed[key] for key in
                               ('focus_id', 'active_id', 'menu_owner_id', 'in_menu_mode')):
        raise ComputerUseError('Native keyboard focus or menu changed; observe again before typing.')
    focus = current['focus_id']
    if not focus or win32gui.GetAncestor(focus, 2) != hwnd:
        raise ComputerUseError(
            f'Keyboard focus is outside the selected window (focus_id={focus}); '
            'select and observe the focused window before typing.')
