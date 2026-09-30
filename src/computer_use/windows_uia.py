from __future__ import annotations

import atexit
import ctypes
import gc
import queue
import threading
import time
from collections import deque
from concurrent.futures import Future
from dataclasses import dataclass
from typing import Any, Callable

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError


@dataclass
class _ThreadState:
    desktop: Any
    pythoncom: Any
    previous_dpi_context: int


@dataclass
class _Request:
    operation: Callable[[Any], Any]
    future: Future


_STOP = object()


def _initialize_thread() -> _ThreadState:
    """Create every UIA/COM object on the thread that will use it."""
    import pythoncom

    pythoncom.CoInitializeEx(pythoncom.COINIT_MULTITHREADED)
    set_dpi = ctypes.WinDLL('user32', use_last_error=True).SetThreadDpiAwarenessContext
    set_dpi.argtypes = [ctypes.c_void_p]
    set_dpi.restype = ctypes.c_void_p
    previous = set_dpi(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
    if not previous:
        pythoncom.CoUninitialize()
        raise ComputerUseError('Cannot establish UI Automation thread DPI awareness.')
    try:
        # Importing pywinauto's UIA backend constructs its process-global IUIA
        # singleton. The import must therefore happen only after COM is ready on
        # this dedicated thread.
        from pywinauto import Desktop

        return _ThreadState(Desktop(backend='uia'), pythoncom, int(previous))
    except BaseException:
        set_dpi(ctypes.c_void_p(previous))
        pythoncom.CoUninitialize()
        raise


def _release_pywinauto_objects() -> None:
    """Release pywinauto's global COM singleton before its apartment closes."""
    from pywinauto.uia_defines import IUIA, _Singleton

    instance = _Singleton._instances.pop(IUIA, None)
    if instance is not None:
        # Release bound COM methods before the owning IUIAutomation interface.
        for name in ('get_focused_element', 'root', 'true_condition', 'iuia'):
            if hasattr(instance, name):
                setattr(instance, name, None)
    gc.collect()


def _finalize_thread(state: _ThreadState) -> None:
    state.desktop = None
    _release_pywinauto_objects()
    set_dpi = ctypes.WinDLL('user32', use_last_error=True).SetThreadDpiAwarenessContext
    set_dpi.argtypes = [ctypes.c_void_p]
    set_dpi.restype = ctypes.c_void_p
    set_dpi(ctypes.c_void_p(state.previous_dpi_context))
    state.pythoncom.CoUninitialize()


class _AutomationRuntime:
    """Single-apartment executor for pywinauto UI Automation operations.

    UIA wrapper objects never cross this boundary. Operations return plain data,
    which prevents a caller thread from destructing a COM proxy after the UIA
    apartment or UIAutomationCore.dll has been torn down.
    """

    def __init__(self, initializer=_initialize_thread, finalizer=_finalize_thread):
        self._initializer = initializer
        self._finalizer = finalizer
        self._requests: queue.Queue = queue.Queue()
        self._ready = threading.Event()
        self._lifecycle_lock = threading.Lock()
        self._closed = False
        self._state = None
        self._startup_error: BaseException | None = None
        self._thread = threading.Thread(target=self._run, name='computer-use-uia', daemon=True)
        self._thread.start()
        self._ready.wait()
        if self._startup_error is not None:
            raise RuntimeError(f'UI Automation thread failed to start: {self._startup_error}')

    def _run(self) -> None:
        try:
            self._state = self._initializer()
        except BaseException as exc:
            self._startup_error = exc
            self._ready.set()
            return
        self._ready.set()
        try:
            while True:
                request = self._requests.get()
                if request is _STOP:
                    return
                try:
                    result = request.operation(self._state.desktop)
                except BaseException as exc:
                    # Never transfer a traceback holding UIA wrappers to another
                    # thread. Only a fresh, data-only exception crosses the boundary.
                    if isinstance(exc, ComputerUseError):
                        forwarded = ComputerUseError(str(exc))
                    else:
                        forwarded = RuntimeError(f'UI Automation {type(exc).__name__}: {exc}')
                    request.future.set_exception(forwarded)
                else:
                    request.future.set_result(result)
        finally:
            self._finalizer(self._state)

    def call(self, operation: Callable[[Any], Any]):
        if threading.current_thread() is self._thread:
            return operation(self._state.desktop)
        future = Future()
        with self._lifecycle_lock:
            if self._closed:
                raise RuntimeError('UI Automation runtime is closed.')
            # Enqueue under the same lock used by close(), so no request can be
            # placed behind the stop marker and wait forever.
            self._requests.put(_Request(operation, future))
        return future.result()

    def close(self) -> None:
        with self._lifecycle_lock:
            if self._closed:
                return
            self._closed = True
            if self._thread.is_alive():
                self._requests.put(_STOP)
        if self._thread.is_alive():
            self._thread.join()


_runtime_lock = threading.Lock()
_runtime: _AutomationRuntime | None = None


def _get_runtime() -> _AutomationRuntime:
    global _runtime
    with _runtime_lock:
        if _runtime is None:
            _runtime = _AutomationRuntime()
        return _runtime


def _close_runtime() -> None:
    global _runtime
    with _runtime_lock:
        runtime, _runtime = _runtime, None
    if runtime is not None:
        runtime.close()


atexit.register(_close_runtime)


def _runtime_id(element):
    value = element.element_info.runtime_id
    return list(value) if value else None


def _focused_element():
    from pywinauto.uia_defines import IUIA
    from pywinauto.uia_element_info import UIAElementInfo
    from pywinauto.controls.uiawrapper import UIAWrapper

    raw = IUIA().get_focused_element()
    return UIAWrapper(UIAElementInfo(raw)) if raw else None


def observe(hwnd, include_text, limit, cancel):
    return _get_runtime().call(
        lambda desktop: _observe(desktop, hwnd, include_text, limit, cancel))


def _observe(desktop, hwnd, include_text, limit, cancel):
    root = desktop.window(handle=hwnd).wrapper_object()
    focus = _focused_element()
    focus_id = _runtime_id(focus) if focus is not None else None
    result = {'focus': focus_id, 'elements': [], 'accessibility': None}
    if not include_text:
        return result
    pending = deque([(root, 0)])
    lines = []
    elements = []
    deadline = time.monotonic() + 4
    truncated = False
    text_budget = 12000
    while pending and len(elements) < limit:
        raise_if_cancel_requested(cancel)
        if time.monotonic() >= deadline:
            truncated = True
            break
        element, depth = pending.popleft()
        info = element.element_info
        box = info.rectangle
        password = bool(info.element.CurrentIsPassword)
        record = {'index': len(elements), 'runtime_id': _runtime_id(element),
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
            pending.extend((child, depth + 1) for child in element.children())
        else:
            truncated = True
    result['elements'] = elements
    focus_record = next((e for e in elements if e['runtime_id'] == focus_id), None)
    result['accessibility'] = {'tree': '\n'.join(lines), 'elements': elements,
                               'focused_element': focus_record, 'truncated': truncated or bool(pending)}
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


def _resolve_element(desktop, hwnd, record, cancel=None):
    """Resolve by runtime identity, never by a potentially shifted list index."""
    pending = deque([desktop.window(handle=hwnd).wrapper_object()])
    deadline = time.monotonic() + 4
    count = 0
    while pending and count < 1000 and time.monotonic() < deadline:
        raise_if_cancel_requested(cancel)
        item = pending.popleft()
        count += 1
        if _runtime_id(item) == record['runtime_id']:
            if bool(item.element_info.element.CurrentIsPassword):
                raise ComputerUseError('Password controls are not exposed by desktop tools.')
            if not item.is_enabled() or not item.is_visible():
                raise ComputerUseError('Control is no longer visible and enabled; observe again.')
            rect = item.rectangle()
            if [rect.left, rect.top, rect.right, rect.bottom] != record['rect']:
                raise ComputerUseError('Control moved since observation; observe again.')
            return item
        pending.extend(item.children())
    raise ComputerUseError('Control is no longer present; observe again.')


def element_action(hwnd, record, action, args, cancel, guard):
    def operation(desktop):
        element = _resolve_element(desktop, hwnd, record, cancel)
        guard()
        if action == 'set_value':
            value = args.get('value')
            if not isinstance(value, str) or len(value) > 4000:
                raise ComputerUseError('value must be text of at most 4000 characters')
            element.iface_value.SetValue(value)
            if element.iface_value.CurrentValue != value:
                raise ComputerUseError('Control did not retain the requested value.')
            return None
        if action == 'perform_secondary_action':
            name = args.get('action')
            if name == 'invoke':
                element.iface_invoke.Invoke()
            elif name == 'expand':
                element.iface_expand_collapse.Expand()
            elif name == 'collapse':
                element.iface_expand_collapse.Collapse()
            elif name == 'select':
                element.iface_selection_item.Select()
            elif name == 'toggle':
                element.iface_toggle.Toggle()
            else:
                raise ComputerUseError('Unsupported secondary action')
            return None
        if action != 'click':
            raise ComputerUseError('element_index is supported by click, set_value and perform_secondary_action')
        box = element.rectangle()
        return (box.left + box.right) // 2, (box.top + box.bottom) // 2

    return _get_runtime().call(operation)


def verify_focus(observation):
    def operation(_desktop):
        current = _focused_element()
        if current is None or observation.focus is None or _runtime_id(current) != observation.focus:
            raise ComputerUseError('Keyboard focus changed or is unknown; observe again before typing.')
        if bool(current.element_info.element.CurrentIsPassword):
            raise ComputerUseError('Password controls are not exposed by desktop tools.')

    _get_runtime().call(operation)
