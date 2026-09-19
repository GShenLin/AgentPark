"""Native Unicode and pointer input, with guaranteed release on cancellation."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import time

from src.runtime_cancellation import raise_if_cancel_requested, sleep_with_cancel
from .contracts import ComputerUseError, integer


ULONG_PTR = ctypes.c_size_t


class MOUSEINPUT(ctypes.Structure):
    _fields_ = [('dx', wintypes.LONG), ('dy', wintypes.LONG), ('mouseData', wintypes.DWORD),
                ('dwFlags', wintypes.DWORD), ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [('wVk', wintypes.WORD), ('wScan', wintypes.WORD), ('dwFlags', wintypes.DWORD),
                ('time', wintypes.DWORD), ('dwExtraInfo', ULONG_PTR)]


class INPUTUNION(ctypes.Union):
    _fields_ = [('mi', MOUSEINPUT), ('ki', KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [('type', wintypes.DWORD), ('value', INPUTUNION)]


KEYS = {'ctrl': 0x11, 'control_l': 0xA2, 'control_r': 0xA3, 'control': 0x11,
        'shift': 0x10, 'shift_l': 0xA0, 'shift_r': 0xA1, 'alt': 0x12, 'alt_l': 0xA4,
        'alt_r': 0xA5, 'enter': 0x0D, 'return': 0x0D, 'tab': 9, 'escape': 0x1B,
        'esc': 0x1B, 'space': 0x20, 'backspace': 8, 'delete': 0x2E, 'insert': 0x2D,
        'left': 0x25, 'up': 0x26, 'right': 0x27, 'down': 0x28, 'home': 0x24,
        'end': 0x23, 'pageup': 0x21, 'pagedown': 0x22, 'prior': 0x21, 'next': 0x22,
        'caps_lock': 0x14, 'period': 0xBE, 'comma': 0xBC, 'slash': 0xBF,
        'kp_add': 0x6B, 'kp_subtract': 0x6D, 'kp_multiply': 0x6A, 'kp_divide': 0x6F,
        'kp_decimal': 0x6E, 'kp_enter': 0x0D}
KEYS.update({f'f{i}': 0x6F + i for i in range(1, 25)})
KEYS.update({f'kp_{i}': 0x60 + i for i in range(10)})
BUTTONS = {'left': (2, 4), 'right': (8, 16), 'middle': (32, 64)}


def send(item):
    api = ctypes.WinDLL('user32', use_last_error=True)
    api.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    api.SendInput.restype = wintypes.UINT
    if api.SendInput(1, ctypes.byref(item), ctypes.sizeof(INPUT)) != 1:
        raise ComputerUseError('Windows rejected input (check target elevation and desktop access).')


def key_event(vk=0, scan=0, flags=0):
    send(INPUT(1, INPUTUNION(ki=KEYBDINPUT(vk, scan, flags, 0, 0))))


def mouse_event(flags, data=0):
    send(INPUT(0, INPUTUNION(mi=MOUSEINPUT(0, 0, data & 0xFFFFFFFF, flags, 0, 0))))


def literal_text(text, cancel, guard):
    if not isinstance(text, str) or not text or len(text) > 4000:
        raise ComputerUseError('text must contain 1-4000 characters')
    encoded = text.encode('utf-16-le')
    for offset in range(0, len(encoded), 2):
        raise_if_cancel_requested(cancel)
        guard()
        code = int.from_bytes(encoded[offset:offset + 2], 'little')
        key_event(scan=code, flags=4)
        try:
            raise_if_cancel_requested(cancel)
        finally:
            key_event(scan=code, flags=6)


def chord(key, cancel, guard):
    if not isinstance(key, str) or not key:
        raise ComputerUseError('key must be a + separated keyboard chord')
    values = []
    for name in key.lower().split('+'):
        name = name.strip()
        if name in KEYS:
            values.append(KEYS[name])
        elif len(name) == 1 and name.isascii() and name.isalnum():
            values.append(ord(name.upper()))
        else:
            raise ComputerUseError(f'Unsupported key: {name}')
    if len(values) > 8:
        raise ComputerUseError('A chord supports at most 8 keys')
    pressed = []
    try:
        for vk in values:
            raise_if_cancel_requested(cancel)
            guard()
            key_event(vk=vk)
            pressed.append(vk)
    finally:
        for vk in reversed(pressed):
            key_event(vk=vk, flags=2)


def click(point, button, count, cancel, guard):
    import win32api
    if button not in BUTTONS:
        raise ComputerUseError('mouse_button must be left, right, or middle')
    integer(count, 'click_count', 1, 3)
    for i in range(count):
        raise_if_cancel_requested(cancel)
        guard(point)
        win32api.SetCursorPos(point)
        down, up = BUTTONS[button]
        mouse_event(down)
        try:
            raise_if_cancel_requested(cancel)
        finally:
            mouse_event(up)
        if i + 1 < count:
            sleep_with_cancel(0.08, cancel)


def drag(start, end, duration_ms, cancel, guard):
    import win32api
    duration = integer(duration_ms, 'duration_ms', 50, 5000) / 1000
    guard(start)
    guard(end)
    win32api.SetCursorPos(start)
    mouse_event(2)
    try:
        began = time.monotonic()
        while True:
            raise_if_cancel_requested(cancel)
            progress = min(1, (time.monotonic() - began) / duration)
            point = tuple(round(a + (b - a) * progress) for a, b in zip(start, end))
            guard(point)
            win32api.SetCursorPos(point)
            if progress >= 1:
                break
            sleep_with_cancel(0.015, cancel)
    finally:
        mouse_event(4)
