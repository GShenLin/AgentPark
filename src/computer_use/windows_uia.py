from __future__ import annotations

import time
from collections import deque
from contextlib import contextmanager

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError


@contextmanager
def automation():
    import pythoncom
    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    try:
        from pywinauto import Desktop
        yield Desktop(backend='uia')
    finally:
        pythoncom.CoUninitialize()


def runtime_id(element):
    value = element.element_info.runtime_id
    return list(value) if value else None


def focused_element():
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo
    from pywinauto.controls.uiawrapper import UIAWrapper
    raw = IUIA().get_focused_element()
    return UIAWrapper(UIAElementInfo(raw)) if raw else None


def observe(hwnd, include_text, limit, cancel):
    with automation() as desktop:
        root = desktop.window(handle=hwnd).wrapper_object()
        focus = focused_element()
        focus_id = runtime_id(focus) if focus is not None else None
        result = {'focus': focus_id, 'elements': [], 'accessibility': None}
        if not include_text:
            return result
        queue = deque([(root, 0)])
        lines = []
        elements = []
        deadline = time.monotonic() + 4
        truncated = False
        text_budget = 12000
        while queue and len(elements) < limit:
            raise_if_cancel_requested(cancel)
            if time.monotonic() >= deadline:
                truncated = True
                break
            element, depth = queue.popleft()
            info = element.element_info
            box = info.rectangle
            password = bool(info.element.CurrentIsPassword)
            record = {'index': len(elements), 'runtime_id': runtime_id(element),
                      'name': '[password]' if password else str(info.name or '')[:240],
                      'control_type': str(info.control_type), 'automation_id': str(info.automation_id or '')[:120],
                      'rect': [box.left, box.top, box.right, box.bottom],
                      'enabled': bool(info.enabled), 'visible': bool(info.visible), 'password': password}
            text_budget -= len(record['name']) + len(record['automation_id'])
            if not password and text_budget > 0 and record['control_type'] in ('Edit', 'Document'):
                from pywinauto.uia_defines import NoPatternInterfaceError
                try:
                    value = str(element.iface_value.CurrentValue or '')[:min(2000, text_budget)]
                    record['value'] = value
                    text_budget -= len(value)
                except NoPatternInterfaceError:
                    record['value_pattern_supported'] = False
            elements.append(record)
            value_text = f" value={record['value']!r}" if 'value' in record else ''
            lines.append(f"{'  ' * depth}{record['index']} {record['control_type']} {record['name']}{value_text}")
            if text_budget <= 0:
                truncated = True
                break
            if depth < 10:
                queue.extend((child, depth + 1) for child in element.children())
            else:
                truncated = True
        result['elements'] = elements
        focus_record = next((e for e in elements if e['runtime_id'] == focus_id), None)
        result['accessibility'] = {'tree': '\n'.join(lines), 'elements': elements,
                                   'focused_element': focus_record, 'truncated': truncated or bool(queue)}
        if focus_record and not focus_record['password'] and focus is not None:
            from pywinauto.uia_defines import NoPatternInterfaceError
            try:
                pattern = focus.iface_text
                result['accessibility']['document_text'] = pattern.DocumentRange.GetText(4000)
                selection = pattern.GetSelection()
                result['accessibility']['selected_text'] = '\n'.join(
                    selection.GetElement(i).GetText(1000) for i in range(min(selection.Length, 4)))
            except NoPatternInterfaceError:
                result['accessibility']['text_pattern_supported'] = False
        return result


def resolve_element(desktop, hwnd, record, cancel=None):
    """Resolve by runtime identity, never by a potentially shifted list index."""
    queue = deque([desktop.window(handle=hwnd).wrapper_object()])
    deadline = time.monotonic() + 4
    count = 0
    while queue and count < 1000 and time.monotonic() < deadline:
        raise_if_cancel_requested(cancel)
        item = queue.popleft()
        count += 1
        if runtime_id(item) == record['runtime_id']:
            if bool(item.element_info.element.CurrentIsPassword):
                raise ComputerUseError('Password controls are not exposed by desktop tools.')
            if not item.is_enabled() or not item.is_visible():
                raise ComputerUseError('Control is no longer visible and enabled; observe again.')
            rect = item.rectangle()
            if [rect.left, rect.top, rect.right, rect.bottom] != record['rect']:
                raise ComputerUseError('Control moved since observation; observe again.')
            return item
        queue.extend(item.children())
    raise ComputerUseError('Control is no longer present; observe again.')


def verify_focus(observation):
    current = focused_element()
    if current is None or observation.focus is None or runtime_id(current) != observation.focus:
        raise ComputerUseError('Keyboard focus changed or is unknown; observe again before typing.')
    if bool(current.element_info.element.CurrentIsPassword):
        raise ComputerUseError('Password controls are not exposed by desktop tools.')
