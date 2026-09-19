from __future__ import annotations

import ctypes
from ctypes import wintypes
import json
import os
from pathlib import Path
import subprocess

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError, integer
from . import windows_input as inputs
from . import windows_uia as uia
from .windows_capture import capture_window


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
                'process_started': created, 'title': win32gui.GetWindowText(hwnd)}

    def list_windows(self):
        import win32gui
        import pywintypes
        result = []
        def collect(hwnd, _):
            if win32gui.IsWindowVisible(hwnd) and win32gui.GetWindowText(hwnd):
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
        for field in ('app', 'pid', 'process_started'):
            if window.get(field) != current[field]:
                raise ComputerUseError('Stale or incomplete window identity; call list_windows/get_window.')
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
        return uia.observe(window['id'], include_text, max_elements, cancel)

    def capture(self, window, cancel):
        import win32gui
        self._desktop_available()
        if win32gui.IsIconic(window['id']):
            raise ComputerUseError('Window is minimized; activate it and observe again.')
        return capture_window(window['id'], cancel)

    def activate(self, window):
        import win32gui
        self._desktop_available()
        with uia.automation() as desktop:
            desktop.window(handle=window['id']).wrapper_object().set_focus()
        if win32gui.GetForegroundWindow() != window['id']:
            raise ComputerUseError('Windows did not activate the requested window; check for a modal dialog.')

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
        self.activate(window)
        rect = self.rectangle(window)
        if rect != observation.rect:
            raise ComputerUseError('Activation changed window bounds; observe again.')

        def guard(point=None):
            raise_if_cancel_requested(cancel)
            self._desktop_available()
            self.resolve(window)
            if self.rectangle(window) != rect or win32gui.GetForegroundWindow() != window['id']:
                raise ComputerUseError('Window or foreground changed during input; observe again.')
            if point is not None:
                if not (rect[0] <= point[0] < rect[2] and rect[1] <= point[1] < rect[3]):
                    raise ComputerUseError('Input point is outside target window.')
                hit = win32gui.WindowFromPoint(point)
                if win32gui.GetAncestor(hit, 2) != window['id']:
                    raise ComputerUseError('Input point is covered by another window; observe it before acting.')

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
            with uia.automation() as desktop:
                element = uia.resolve_element(desktop, window['id'], observation.elements[index], cancel)
                guard()
                if action == 'set_value':
                    value = args.get('value')
                    if not isinstance(value, str) or len(value) > 4000:
                        raise ComputerUseError('value must be text of at most 4000 characters')
                    element.iface_value.SetValue(value)
                    if element.iface_value.CurrentValue != value:
                        raise ComputerUseError('Control did not retain the requested value.')
                    return
                if action == 'perform_secondary_action':
                    name = args.get('action')
                    if name == 'invoke': element.iface_invoke.Invoke()
                    elif name == 'expand': element.iface_expand_collapse.Expand()
                    elif name == 'collapse': element.iface_expand_collapse.Collapse()
                    elif name == 'select': element.iface_selection_item.Select()
                    elif name == 'toggle': element.iface_toggle.Toggle()
                    else: raise ComputerUseError('Unsupported secondary action')
                    return
                if action != 'click':
                    raise ComputerUseError('element_index is supported by click, set_value and perform_secondary_action')
                box = element.rectangle()
                click_point = ((box.left + box.right) // 2, (box.top + box.bottom) // 2)
        else:
            click_point = point() if action in ('click', 'scroll') else None
        if action == 'click':
            inputs.click(click_point, args.get('mouse_button', 'left'), args.get('click_count', 1), cancel, guard)
        elif action == 'drag':
            inputs.drag(point('from_x', 'from_y'), point('to_x', 'to_y'), args.get('duration_ms', 250), cancel, guard)
        elif action == 'scroll':
            guard(click_point)
            win32api.SetCursorPos(click_point)
            for key, flag, sign in [('scrollY', 0x800, -1), ('scrollX', 0x1000, 1)]:
                value = integer(args.get(key, 0), key, -12000, 12000)
                if value:
                    guard(click_point)
                    inputs.mouse_event(flag, value * sign)
        elif action in ('type_text', 'press_key'):
            with uia.automation():
                uia.verify_focus(observation)
                def keyboard_guard():
                    guard()
                    uia.verify_focus(observation)
                if action == 'type_text':
                    inputs.literal_text(args.get('text'), cancel, keyboard_guard)
                else:
                    inputs.chord(args.get('key'), cancel, keyboard_guard)
        else:
            raise ComputerUseError(f'Unsupported action or missing element_index: {action}')
