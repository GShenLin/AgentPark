from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError, PointerFeedback, PointerPoint, integer
from . import windows_input as inputs
from . import windows_uia as uia
from . import windows_state as native
from .windows_capture import capture_window


def _process_started_instant(value, field):
    if not isinstance(value, str):
        raise ComputerUseError(f'{field} must be an ISO-8601 timestamp with a timezone.')
    try:
        instant = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ComputerUseError(
            f'{field} must be an ISO-8601 timestamp with a timezone.') from exc
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ComputerUseError(f'{field} must be an ISO-8601 timestamp with a timezone.')
    return instant.astimezone(timezone.utc)


class WindowsBackend:
    """Windows HWND identity, WGC observations, UIA controls and native input."""

    def __init__(self):
        if os.name != 'nt':
            raise ComputerUseError('Window-scoped Computer Use currently requires Windows.')
        from .windows_session import WindowsDesktopSession
        self.desktop_session = WindowsDesktopSession()

    @staticmethod
    def _window(hwnd):
        import win32api
        import win32gui
        import win32process
        if not win32gui.IsWindow(hwnd):
            raise ComputerUseError('Window no longer exists; call list_windows.')
        _, pid = win32process.GetWindowThreadProcessId(hwnd)
        handle = win32api.OpenProcess(0x1000, False, pid)
        try:
            query = ctypes.WinDLL('kernel32', use_last_error=True).QueryFullProcessImageNameW
            query.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
            query.restype = wintypes.BOOL
            size = wintypes.DWORD(32768)
            buffer = ctypes.create_unicode_buffer(size.value)
            if not query(int(handle), 0, buffer, ctypes.byref(size)):
                raise ctypes.WinError(ctypes.get_last_error())
            path = buffer.value
            created = win32process.GetProcessTimes(handle)['CreationTime'].isoformat()
        finally:
            handle.Close()
        return {'id': hwnd, 'app': 'process:' + path, 'pid': pid,
                'process_started': created, 'title': win32gui.GetWindowText(hwnd),
                **native.window_details(hwnd)}

    def list_windows(self):
        import win32gui
        import pywintypes
        result = []
        def collect(hwnd, _):
            if win32gui.IsWindowVisible(hwnd):
                try:
                    result.append(self._window(hwnd))
                except pywintypes.error as exc:
                    # Protected/terminated processes are not controllable application targets.
                    if exc.winerror not in (5, 87, 1400):
                        raise
        win32gui.EnumWindows(collect, None)
        return result

    def list_apps(self):
        apps = {}
        for window in self.list_windows():
            app = apps.setdefault(window['app'], {'id': window['app'],
                                  'displayName': Path(window['app'][8:]).stem, 'windows': []})
            app['windows'].append(window)
        completed = subprocess.run(
            ['powershell.exe', '-NoProfile', '-NonInteractive', '-Command',
             "[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new(); @(Get-StartApps) | ConvertTo-Json -Compress"],
            capture_output=True, encoding='utf-8', timeout=15, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW)
        installed = json.loads(completed.stdout or '[]')
        if isinstance(installed, dict):
            installed = [installed]
        for item in installed:
            app_id = 'aumid:' + item['AppID']
            apps[app_id] = {'id': app_id, 'displayName': item['Name'], 'windows': []}
        return list(apps.values())

    def resolve(self, window):
        if not isinstance(window, dict):
            raise ComputerUseError('window must be an object returned by list_windows/get_window')
        current = self._window(integer(window.get('id'), 'window.id', 1))
        for field in ('app', 'pid'):
            if window.get(field) != current[field]:
                raise ComputerUseError(
                    f'Window identity field {field} does not match the current window; '
                    'call list_windows/get_window.')
        supplied_started = _process_started_instant(
            window.get('process_started'), 'window.process_started')
        current_started = _process_started_instant(
            current['process_started'], 'current process_started')
        if supplied_started != current_started:
            raise ComputerUseError(
                'Window identity field process_started does not match the current process; '
                'call list_windows/get_window.')
        return current

    def rectangle(self, window):
        rect = wintypes.RECT()
        result = ctypes.WinDLL('dwmapi').DwmGetWindowAttribute(
            wintypes.HWND(window['id']), 9, ctypes.byref(rect), ctypes.sizeof(rect))
        if result != 0:
            raise ComputerUseError(f'Cannot read window frame bounds: HRESULT {result}')
        return rect.left, rect.top, rect.right, rect.bottom

    @staticmethod
    def _desktop_available():
        api = ctypes.WinDLL('user32', use_last_error=True)
        api.OpenInputDesktop.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        api.OpenInputDesktop.restype = wintypes.HANDLE
        api.CloseDesktop.argtypes = [wintypes.HANDLE]
        handle = api.OpenInputDesktop(0, False, 1)
        if not handle:
            raise ComputerUseError('Interactive desktop is locked or unavailable.')
        api.CloseDesktop(handle)

    def observe(self, window, include_text, max_elements, cancel):
        self._desktop_available()
        state = uia.observe(window['id'], include_text, max_elements, cancel)
        state['native_focus'] = native.input_state(window['id'])
        windows = self.list_windows()  # EnumWindows order is top to bottom.
        state['z_order'] = {w['id']: len(windows) - index for index, w in enumerate(windows)}
        state['related_windows'] = [w for w in windows
                                   if w['pid'] == window['pid'] and w['id'] != window['id']]
        state['transient_windows'] = [w for w in state['related_windows']
                                      if w['owner_id'] == window['id'] or
                                      (w['thread_id'] == window['thread_id'] and w['is_tool_window'])]
        return state

    def capture(self, window, cancel, mode):
        import win32gui
        self._desktop_available()
        if not win32gui.IsWindowVisible(window['id']):
            raise ComputerUseError('Window is no longer visible; call list_windows and observe the current window.')
        if win32gui.IsIconic(window['id']):
            raise ComputerUseError('Window is minimized; activate it and observe again.')
        if mode == 'visible_region':
            from PIL import ImageGrab
            raise_if_cancel_requested(cancel)
            return ImageGrab.grab(bbox=self.rectangle(window), all_screens=True)
        return capture_window(window['id'], cancel)

    def activate(self, window):
        self._desktop_available()
        native.activate(window['id'])

    def launch(self, app):
        self._desktop_available()
        if app.startswith('process:'):
            path = Path(app[8:])
            if not path.is_absolute() or path.suffix.lower() != '.exe' or not path.is_file():
                raise ComputerUseError('process: requires an existing absolute .exe path')
            subprocess.Popen([str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif app.startswith('aumid:') and any(a['id'] == app for a in self.list_apps()):
            os.startfile('shell:AppsFolder\\' + app[6:])
        else:
            raise ComputerUseError('Use an installed aumid: identifier from list_apps or process:<absolute.exe>.')

    def act(self, action, window, observation, args, cancel):
        import win32api
        import win32gui
        foreground = win32gui.GetForegroundWindow()
        if not native.accepts_pointer(window['id'], foreground):
            self.activate(window)
        rect = self.rectangle(window)
        if rect != observation.rect:
            raise ComputerUseError('Activation changed window bounds; observe again.')

        def guard(point=None):
            raise_if_cancel_requested(cancel)
            self._desktop_available()
            self.resolve(window)
            if self.rectangle(window) != rect or not native.accepts_pointer(window['id'], win32gui.GetForegroundWindow()):
                raise ComputerUseError('Window or foreground changed during input; observe again.')
            if point is not None:
                if not (rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]):
                    raise ComputerUseError('Input point is outside target window.')
                hit = win32gui.WindowFromPoint(point)
                if win32gui.GetAncestor(hit, 2) != window['id']:
                    raise ComputerUseError(
                        f'Input point is covered by window id={win32gui.GetAncestor(hit, 2)}; '
                        'call list_windows/get_window and observe that window before acting.')

        def point(x_key='x', y_key='y'):
            x = integer(args.get(x_key), x_key, 0, rect[2] - rect[0] - 1)
            y = integer(args.get(y_key), y_key, 0, rect[3] - rect[1] - 1)
            return rect[0] + x, rect[1] + y

        guard()
        index = args.get('element_index')
        if index is not None:
            integer(index, 'element_index', 0, len(observation.elements) - 1)
            if args.get('x') is not None or args.get('y') is not None:
                raise ComputerUseError('Choose element_index or coordinates, not both.')
            click_point = uia.element_action(
                window['id'], observation.elements[index], action, args, cancel, guard)
            if action in ('set_value', 'perform_secondary_action'):
                return
        else:
            click_point = point() if action in ('click', 'scroll') else None
        if action == 'click':
            inputs.click(click_point, args.get('mouse_button', 'left'), args.get('click_count', 1), cancel, guard)
            return PointerFeedback((PointerPoint('click', *click_point),))
        elif action == 'drag':
            start, end = point('from_x', 'from_y'), point('to_x', 'to_y')
            inputs.drag(start, end, args.get('duration_ms', 250), cancel, guard)
            return PointerFeedback((PointerPoint('start', *start), PointerPoint('end', *end)))
        elif action == 'scroll':
            guard(click_point)
            win32api.SetCursorPos(click_point)
            for key, flag, sign in [('scrollY', 0x800, -1), ('scrollX', 0x1000, 1)]:
                value = integer(args.get(key, 0), key, -12000, 12000)
                if value:
                    guard(click_point)
                    inputs.mouse_event(flag, value * sign)
            return PointerFeedback((PointerPoint('scroll', *click_point),))
        elif action in ('type_text', 'press_key'):
            native.verify_keyboard(window['id'], observation.native_focus)
            uia.verify_focus(observation)
            def keyboard_guard():
                guard()
                native.verify_keyboard(window['id'], observation.native_focus)
                uia.verify_focus(observation)
            if action == 'type_text':
                inputs.literal_text(args.get('text'), cancel, keyboard_guard)
            else:
                inputs.chord(args.get('key'), cancel, keyboard_guard)
        else:
            raise ComputerUseError(f'Unsupported action or missing element_index: {action}')
