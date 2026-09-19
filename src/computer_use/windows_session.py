"""Shared desktop exclusion and observation epoch across AgentPark processes."""
from contextlib import contextmanager
import ctypes
import mmap
import struct

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError


class WindowsDesktopSession:
    def __init__(self):
        import win32event
        self.mutex = win32event.CreateMutex(None, False, 'Local\\AgentPark.ComputerUse.Input')
        self.memory = mmap.mmap(-1, 8, tagname='Local\\AgentPark.ComputerUse.Epoch')

    @contextmanager
    def access(self, cancel):
        import win32event
        while True:
            raise_if_cancel_requested(cancel)
            result = win32event.WaitForSingleObject(self.mutex, 50)
            if result in (0, 0x80):
                break
            if result != 0x102:
                raise ComputerUseError('Cannot acquire desktop input ownership')
        try:
            if result == 0x80:
                self.bump()  # A terminated process may have left an uncertain action.
            # Keep WGC pixels, UIA rectangles and cursor coordinates in one space
            # regardless of the hosting Python process's existing DPI awareness.
            set_dpi = ctypes.WinDLL('user32', use_last_error=True).SetThreadDpiAwarenessContext
            set_dpi.argtypes = [ctypes.c_void_p]
            set_dpi.restype = ctypes.c_void_p
            previous = set_dpi(ctypes.c_void_p(-4))  # PER_MONITOR_AWARE_V2
            if not previous:
                raise ComputerUseError('Cannot establish per-monitor pixel coordinates.')
            try:
                yield
            finally:
                set_dpi(previous)
        finally:
            win32event.ReleaseMutex(self.mutex)

    def epoch(self):
        return struct.unpack('<Q', self.memory[:8])[0]

    def bump(self):
        value = self.epoch() + 1
        self.memory[:8] = struct.pack('<Q', value)
        return value
