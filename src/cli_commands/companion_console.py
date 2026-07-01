from __future__ import annotations

import ctypes
import os
import queue
import shutil
import sys
import threading
from dataclasses import dataclass
from typing import Literal


EventKind = Literal["key", "resize"]


@dataclass(frozen=True)
class ConsoleEvent:
    kind: EventKind
    key: str = ""
    text: str = ""
    ctrl: bool = False
    alt: bool = False
    shift: bool = False


STD_INPUT_HANDLE = -10
STD_OUTPUT_HANDLE = -11
KEY_EVENT = 0x0001
WINDOW_BUFFER_SIZE_EVENT = 0x0004
ENABLE_PROCESSED_INPUT = 0x0001
ENABLE_LINE_INPUT = 0x0002
ENABLE_ECHO_INPUT = 0x0004
ENABLE_WINDOW_INPUT = 0x0008
ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
DISABLE_NEWLINE_AUTO_RETURN = 0x0008
LEFT_ALT_PRESSED = 0x0002
LEFT_CTRL_PRESSED = 0x0008
RIGHT_ALT_PRESSED = 0x0001
RIGHT_CTRL_PRESSED = 0x0004
SHIFT_PRESSED = 0x0010

VK_BACK = 0x08
VK_TAB = 0x09
VK_RETURN = 0x0D
VK_ESCAPE = 0x1B
VK_SPACE = 0x20
VK_PRIOR = 0x21
VK_NEXT = 0x22
VK_END = 0x23
VK_HOME = 0x24
VK_LEFT = 0x25
VK_UP = 0x26
VK_RIGHT = 0x27
VK_DOWN = 0x28
VK_INSERT = 0x2D
VK_DELETE = 0x2E

VIRTUAL_KEYS = {
    VK_BACK: "backspace",
    VK_TAB: "tab",
    VK_RETURN: "enter",
    VK_ESCAPE: "escape",
    VK_PRIOR: "pageup",
    VK_NEXT: "pagedown",
    VK_END: "end",
    VK_HOME: "home",
    VK_LEFT: "left",
    VK_UP: "up",
    VK_RIGHT: "right",
    VK_DOWN: "down",
    VK_INSERT: "insert",
    VK_DELETE: "delete",
}


class COORD(ctypes.Structure):
    _fields_ = [("X", ctypes.c_short), ("Y", ctypes.c_short)]


class KEY_EVENT_RECORD(ctypes.Structure):
    _fields_ = [
        ("bKeyDown", ctypes.c_int32),
        ("wRepeatCount", ctypes.c_uint16),
        ("wVirtualKeyCode", ctypes.c_uint16),
        ("wVirtualScanCode", ctypes.c_uint16),
        ("uChar", ctypes.c_wchar),
        ("dwControlKeyState", ctypes.c_uint32),
    ]


class WINDOW_BUFFER_SIZE_RECORD(ctypes.Structure):
    _fields_ = [("dwSize", COORD)]


class EVENT_UNION(ctypes.Union):
    _fields_ = [
        ("KeyEvent", KEY_EVENT_RECORD),
        ("WindowBufferSizeEvent", WINDOW_BUFFER_SIZE_RECORD),
    ]


class INPUT_RECORD(ctypes.Structure):
    _fields_ = [("EventType", ctypes.c_uint16), ("Event", EVENT_UNION)]


class WindowsConsole:
    def __init__(self) -> None:
        self.kernel32 = ctypes.windll.kernel32
        self.input_handle = self.kernel32.GetStdHandle(STD_INPUT_HANDLE)
        self.output_handle = self.kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
        self._input_mode: int | None = None
        self._output_mode: int | None = None

    @classmethod
    def is_available(cls) -> bool:
        if os.name != "nt":
            return False
        try:
            console = cls()
            return console.is_console_handle(console.input_handle) and console.is_console_handle(console.output_handle)
        except Exception:
            return False

    @classmethod
    def availability_report(cls) -> str:
        if os.name != "nt":
            return "os is not Windows"
        try:
            console = cls()
            input_is_console = console.is_console_handle(console.input_handle)
            output_is_console = console.is_console_handle(console.output_handle)
            return (
                f"stdin_console={input_is_console}, stdout_console={output_is_console}, "
                f"stdin_isatty={sys.stdin.isatty()}, stdout_isatty={sys.stdout.isatty()}, "
                f"stdin_encoding={getattr(sys.stdin, 'encoding', '')}, stdout_encoding={getattr(sys.stdout, 'encoding', '')}"
            )
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"

    def is_console_handle(self, handle: int) -> bool:
        mode = ctypes.c_uint32()
        return bool(self.kernel32.GetConsoleMode(handle, ctypes.byref(mode)))

    def __enter__(self) -> WindowsConsole:
        self._input_mode = self._get_mode(self.input_handle)
        self._output_mode = self._get_mode(self.output_handle)
        raw_input_mode = (self._input_mode | ENABLE_WINDOW_INPUT) & ~ENABLE_LINE_INPUT & ~ENABLE_ECHO_INPUT
        raw_input_mode = raw_input_mode & ~ENABLE_PROCESSED_INPUT
        self.kernel32.SetConsoleMode(self.input_handle, raw_input_mode)
        self.kernel32.SetConsoleMode(
            self.output_handle,
            self._output_mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING,
        )
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if self._input_mode is not None:
            self.kernel32.SetConsoleMode(self.input_handle, self._input_mode)
        if self._output_mode is not None:
            self.kernel32.SetConsoleMode(self.output_handle, self._output_mode)

    def _get_mode(self, handle: int) -> int:
        mode = ctypes.c_uint32()
        if not self.kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
            raise OSError("GetConsoleMode failed")
        return int(mode.value)

    def read_event(self) -> ConsoleEvent:
        while True:
            record = INPUT_RECORD()
            read = ctypes.c_uint32()
            ok = self.kernel32.ReadConsoleInputW(
                self.input_handle,
                ctypes.byref(record),
                1,
                ctypes.byref(read),
            )
            if not ok:
                raise OSError("ReadConsoleInputW failed")
            event = self._map_record(record)
            if event is not None:
                return event

    def _map_record(self, record: INPUT_RECORD) -> ConsoleEvent | None:
        if record.EventType == WINDOW_BUFFER_SIZE_EVENT:
            return ConsoleEvent(kind="resize")
        if record.EventType != KEY_EVENT:
            return None
        key = record.Event.KeyEvent
        if not key.bKeyDown:
            return None
        repeat_count = max(1, int(key.wRepeatCount))
        flags = int(key.dwControlKeyState)
        ctrl = bool(flags & (LEFT_CTRL_PRESSED | RIGHT_CTRL_PRESSED))
        alt = bool(flags & (LEFT_ALT_PRESSED | RIGHT_ALT_PRESSED))
        shift = bool(flags & SHIFT_PRESSED)
        name = VIRTUAL_KEYS.get(int(key.wVirtualKeyCode), "")
        if not name and key.uChar:
            name = "char"
        text = key.uChar * repeat_count if name == "char" else ""
        if ctrl and key.uChar and ord(key.uChar) < 32:
            letter = chr(ord(key.uChar) + 96)
            name = letter
            text = ""
        return ConsoleEvent(kind="key", key=name, text=text, ctrl=ctrl, alt=alt, shift=shift)


class ConsoleEventReader:
    def __init__(self, console: WindowsConsole) -> None:
        self.console = console
        self.events: queue.Queue[ConsoleEvent] = queue.Queue()
        self.thread = threading.Thread(target=self._read_loop, name="companion-console-input", daemon=True)

    def start(self) -> None:
        self.thread.start()

    def get(self, timeout: float) -> ConsoleEvent | None:
        try:
            return self.events.get(timeout=timeout)
        except queue.Empty:
            return None

    def _read_loop(self) -> None:
        while True:
            try:
                self.events.put(self.console.read_event())
            except Exception:
                self.events.put(ConsoleEvent(kind="key", key="error"))
                return


MSVCRT_EXTENDED_KEYS = {
    "H": "up",
    "P": "down",
    "K": "left",
    "M": "right",
    "G": "home",
    "O": "end",
    "I": "pageup",
    "Q": "pagedown",
    "R": "insert",
    "S": "delete",
}


class MsvcrtConsole:
    backend_name = "msvcrt"

    @classmethod
    def is_available(cls) -> bool:
        if os.name != "nt":
            return False
        try:
            import msvcrt  # noqa: F401

            return sys.stdin.isatty() and sys.stdout.isatty()
        except Exception:
            return False

    @classmethod
    def availability_report(cls) -> str:
        if os.name != "nt":
            return "os is not Windows"
        return (
            f"stdin_isatty={sys.stdin.isatty()}, stdout_isatty={sys.stdout.isatty()}, "
            f"stdin_encoding={getattr(sys.stdin, 'encoding', '')}, stdout_encoding={getattr(sys.stdout, 'encoding', '')}"
        )

    def __enter__(self) -> MsvcrtConsole:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        return None

    def read_event(self) -> ConsoleEvent:
        import msvcrt

        while True:
            ch = msvcrt.getwch()
            if ch in ("\x00", "\xe0"):
                key = MSVCRT_EXTENDED_KEYS.get(msvcrt.getwch(), "")
                if key:
                    return ConsoleEvent(kind="key", key=key)
                continue
            if ch in ("\r", "\n"):
                return ConsoleEvent(kind="key", key="enter")
            if ch == "\b":
                return ConsoleEvent(kind="key", key="backspace")
            if ch == "\t":
                return ConsoleEvent(kind="key", key="tab")
            if ch == "\x1b":
                return ConsoleEvent(kind="key", key="escape")
            if ch == "\x03":
                return ConsoleEvent(kind="key", key="c", ctrl=True)
            if ch == "\x04":
                return ConsoleEvent(kind="key", key="d", ctrl=True)
            if ch == "\x15":
                return ConsoleEvent(kind="key", key="u", ctrl=True)
            if ch == "\x01":
                return ConsoleEvent(kind="key", key="a", ctrl=True)
            if ch == "\x05":
                return ConsoleEvent(kind="key", key="e", ctrl=True)
            if ch == "\x0c":
                return ConsoleEvent(kind="key", key="l", ctrl=True)
            if ord(ch) < 32:
                continue
            return ConsoleEvent(kind="key", key="char", text=ch)


class TerminalScreen:
    def __init__(self, *, title: str = "AgentPark Companion") -> None:
        self.stdout = sys.stdout
        self.title = title
        self._output_mode: int | None = None

    def __enter__(self) -> TerminalScreen:
        self._enable_virtual_terminal_output()
        self.write(f"\x1b]0;{self.title}\x07\x1b[?1049h\x1b[?25l\x1b[2J\x1b[H")
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.write("\x1b[?25h\x1b[0m\x1b[?1049l\n")
        self._restore_output_mode()

    def size(self) -> tuple[int, int]:
        size = shutil.get_terminal_size((100, 30))
        return max(40, size.columns), max(12, size.lines)

    def render(self, text: str) -> None:
        self.write("\x1b[H\x1b[2J" + text)

    def write(self, text: str) -> None:
        self.stdout.write(text)
        self.stdout.flush()

    def _enable_virtual_terminal_output(self) -> None:
        if os.name != "nt":
            return
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            mode = ctypes.c_uint32()
            if not kernel32.GetConsoleMode(handle, ctypes.byref(mode)):
                return
            self._output_mode = int(mode.value)
            next_mode = self._output_mode | ENABLE_VIRTUAL_TERMINAL_PROCESSING | DISABLE_NEWLINE_AUTO_RETURN
            kernel32.SetConsoleMode(handle, next_mode)
        except Exception:
            return

    def _restore_output_mode(self) -> None:
        if os.name != "nt" or self._output_mode is None:
            return
        try:
            kernel32 = ctypes.windll.kernel32
            handle = kernel32.GetStdHandle(STD_OUTPUT_HANDLE)
            kernel32.SetConsoleMode(handle, self._output_mode)
        except Exception:
            return
