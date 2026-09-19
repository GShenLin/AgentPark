"""Opt-in desktop smoke test. Creates and controls only its own disposable window."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
TITLE = 'AgentPark Computer Use Validation'


def fixture():
    import win32api
    import win32con
    import win32gui
    def procedure(hwnd, message, wp, lp):
        if message == win32con.WM_DESTROY:
            win32gui.PostQuitMessage(0)
            return 0
        if message == win32con.WM_COMMAND and wp & 0xFFFF == 2:
            win32gui.SetWindowText(hwnd, TITLE + ' - clicked')
            return 0
        if message == win32con.WM_MOUSEWHEEL:
            win32gui.SetWindowText(hwnd, TITLE + ' - scrolled')
            return 0
        if message == win32con.WM_LBUTTONUP and (lp >> 16) & 0xFFFF >= 200:
            win32gui.SetWindowText(hwnd, TITLE + ' - dragged')
            return 0
        return win32gui.DefWindowProc(hwnd, message, wp, lp)
    wc = win32gui.WNDCLASS()
    wc.lpszClassName = 'AgentParkComputerUseValidation'
    wc.lpfnWndProc = procedure
    wc.hInstance = win32api.GetModuleHandle(None)
    wc.hbrBackground = win32con.COLOR_WINDOW + 1
    win32gui.RegisterClass(wc)
    hwnd = win32gui.CreateWindow(wc.lpszClassName, TITLE, win32con.WS_OVERLAPPEDWINDOW,
                                 150, 150, 620, 360, 0, 0, wc.hInstance, None)
    win32gui.CreateWindowEx(win32con.WS_EX_CLIENTEDGE, 'EDIT', '',
                           win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_TABSTOP | win32con.ES_AUTOHSCROLL,
                           30, 40, 500, 40, hwnd, 1, wc.hInstance, None)
    win32gui.CreateWindow('BUTTON', 'Test click', win32con.WS_CHILD | win32con.WS_VISIBLE,
                         30, 110, 130, 35, hwnd, 2, wc.hInstance, None)
    win32gui.ShowWindow(hwnd, win32con.SW_SHOW)
    win32gui.UpdateWindow(hwnd)
    win32gui.PumpMessages()


def run():
    import win32con
    import win32gui
    from types import SimpleNamespace
    from src.tool.base_tool import BaseTool
    child = subprocess.Popen([sys.executable, '-X', 'utf8', __file__, '--fixture'], creationflags=subprocess.CREATE_NO_WINDOW)
    agent = SimpleNamespace(config={})
    tools = BaseTool(agent)
    tools.addTool('computer_use_tools')
    def call(name, **args):
        result = json.loads(tools.execute_tool(name, args))
        if result.get('status') != 'success':
            raise RuntimeError(f'{name}: {result}')
        return result
    hwnd = None
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            matches = [w for w in call('list_windows')['windows'] if w['pid'] == child.pid and w['title'] == TITLE]
            if matches:
                window = matches[0]
                hwnd = window['id']
                break
            time.sleep(0.1)
        else:
            raise RuntimeError('Test window did not start')
        call('activate_window', window=window)
        def observe(): return call('get_window_state', window=window, include_text=True)
        state = observe()
        print(json.dumps({'capture': [state['width'], state['height']], 'elements': len(state['accessibility']['elements'])}))
        edit = next(e for e in state['accessibility']['elements'] if e['control_type'] == 'Edit')
        call('click', window=window, observation_id=state['observation_id'], element_index=edit['index'])
        state = observe()
        text = 'AgentPark \u4e2d\u6587 \U0001f600 {literal}'
        call('type_text', window=window, observation_id=state['observation_id'], text=text)
        time.sleep(0.15)
        def edit_value():
            from src.computer_use.windows_uia import automation
            with automation() as desktop:
                return desktop.window(handle=hwnd).child_window(control_type='Edit').wrapper_object().iface_value.CurrentValue
        assert edit_value() == text, repr(edit_value())
        state = observe()
        call('press_key', window=window, observation_id=state['observation_id'], key='Control_L+a')
        state = observe()
        call('type_text', window=window, observation_id=state['observation_id'], text='Keyboard verified')
        time.sleep(0.1)
        assert edit_value() == 'Keyboard verified', repr(edit_value())
        state = observe()
        edit = next(e for e in state['accessibility']['elements'] if e['control_type'] == 'Edit')
        call('set_value', window=window, observation_id=state['observation_id'], element_index=edit['index'], value='UIA verified')
        assert edit_value() == 'UIA verified'
        state = observe()
        button = next(e for e in state['accessibility']['elements'] if e['name'] == 'Test click')
        box = button['rect']
        x = (box[0] + box[2]) // 2 - state['bounds']['left']
        y = (box[1] + box[3]) // 2 - state['bounds']['top']
        call('click', window=window, observation_id=state['observation_id'], x=x, y=y,
             screenshotId=state['screenshotId'])
        time.sleep(0.1)
        assert win32gui.GetWindowText(hwnd).endswith('clicked')
        state = observe()
        call('scroll', window=window, observation_id=state['observation_id'], x=300, y=270, scrollY=120)
        time.sleep(0.1)
        assert win32gui.GetWindowText(hwnd).endswith('scrolled')
        state = observe()
        call('drag', window=window, observation_id=state['observation_id'], from_x=280, from_y=270,
             to_x=400, to_y=280)
        time.sleep(0.1)
        assert win32gui.GetWindowText(hwnd).endswith('dragged')
        state = observe()
        button = next(e for e in state['accessibility']['elements'] if e['name'] == 'Test click')
        call('perform_secondary_action', window=window, observation_id=state['observation_id'],
             element_index=button['index'], action='invoke')
        time.sleep(0.1)
        assert win32gui.GetWindowText(hwnd).endswith('clicked')
        assert any(a['id'] == window['app'] for a in call('list_apps')['apps'])
        print('PASS: WGC, UIA, element/coordinate clicks, Unicode/emoji, key chord, set_value, scroll, drag, invoke, app listing')
    finally:
        if hwnd and win32gui.IsWindow(hwnd):
            win32gui.PostMessage(hwnd, win32con.WM_CLOSE, 0, 0)
        try: child.wait(timeout=5)
        except subprocess.TimeoutExpired:
            child.terminate()
            child.wait(timeout=5)


if __name__ == '__main__':
    fixture() if '--fixture' in sys.argv else run()
