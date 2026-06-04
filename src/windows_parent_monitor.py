import ctypes
import os
import sys
import threading
from ctypes import wintypes


_TH32CS_SNAPPROCESS = 0x00000002
_SYNCHRONIZE = 0x00100000
_INFINITE = 0xFFFFFFFF
_WAIT_OBJECT_0 = 0x00000000
_INVALID_HANDLE_VALUE = ctypes.c_void_p(-1).value


class _PROCESSENTRY32W(ctypes.Structure):
    _fields_ = [
        ("dwSize", wintypes.DWORD),
        ("cntUsage", wintypes.DWORD),
        ("th32ProcessID", wintypes.DWORD),
        ("th32DefaultHeapID", ctypes.c_size_t),
        ("th32ModuleID", wintypes.DWORD),
        ("cntThreads", wintypes.DWORD),
        ("th32ParentProcessID", wintypes.DWORD),
        ("pcPriClassBase", ctypes.c_long),
        ("dwFlags", wintypes.DWORD),
        ("szExeFile", wintypes.WCHAR * wintypes.MAX_PATH),
    ]


def _kernel32():
    return ctypes.WinDLL("kernel32", use_last_error=True)


def get_parent_pid() -> int:
    if os.name != "nt":
        return 0

    kernel32 = _kernel32()
    snapshot = kernel32.CreateToolhelp32Snapshot(_TH32CS_SNAPPROCESS, 0)
    if snapshot == _INVALID_HANDLE_VALUE:
        return 0

    entry = _PROCESSENTRY32W()
    entry.dwSize = ctypes.sizeof(_PROCESSENTRY32W)
    current_pid = os.getpid()

    try:
        found = kernel32.Process32FirstW(snapshot, ctypes.byref(entry))
        while found:
            if int(entry.th32ProcessID) == current_pid:
                return int(entry.th32ParentProcessID)
            found = kernel32.Process32NextW(snapshot, ctypes.byref(entry))
    finally:
        kernel32.CloseHandle(snapshot)

    return 0


def start_frozen_parent_exit_monitor(exit_func=None) -> None:
    if os.name != "nt":
        return
    if not getattr(sys, "frozen", False):
        return

    parent_pid = get_parent_pid()
    if parent_pid <= 0 or parent_pid == os.getpid():
        return

    kernel32 = _kernel32()
    parent_handle = kernel32.OpenProcess(_SYNCHRONIZE, False, parent_pid)
    if not parent_handle:
        return

    if exit_func is None:
        exit_func = lambda: os._exit(0)

    def _watch_parent() -> None:
        try:
            result = kernel32.WaitForSingleObject(parent_handle, _INFINITE)
            if result == _WAIT_OBJECT_0:
                exit_func()
        finally:
            kernel32.CloseHandle(parent_handle)

    threading.Thread(target=_watch_parent, name="parent-exit-monitor", daemon=True).start()


__all__ = ["get_parent_pid", "start_frozen_parent_exit_monitor"]
