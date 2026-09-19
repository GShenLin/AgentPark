"""Windows Workbench transport and user-bound protection for the ACME account."""
from __future__ import annotations

import ctypes
import shlex
import subprocess
import time
from pathlib import Path

WORKBENCH = Path(r'C:\Program Files\workbench\workbench.exe')
INSTANCE = 'i-2vcftcvzh0qn016tsm2e'
REMOTE_PYTHON = '/opt/agentpark-coordinator/.venv/bin/python'
REMOTE_HELPER = '/opt/agentpark-coordinator/deploy/peer-network/tls_server.py'


def run(*args: str) -> str:
    result = subprocess.run([str(WORKBENCH), *args], capture_output=True, encoding='utf-8', timeout=180,
                            creationflags=subprocess.CREATE_NO_WINDOW)
    if result.returncode:
        raise RuntimeError(f'Workbench {args[0]} failed with exit code {result.returncode}.')
    return result.stdout.strip()


def ensure_daemon():
    def running():
        status = subprocess.run([str(WORKBENCH), 'daemon', 'status'], capture_output=True,
                                encoding='utf-8', timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        return status.returncode == 0 and status.stdout.strip() == 'Daemon is running.'
    if running():
        return
    subprocess.Popen([str(WORKBENCH), 'daemon', 'start'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=subprocess.CREATE_NO_WINDOW)
    for _ in range(20):
        if running():
            return
        time.sleep(1)
    raise RuntimeError('Workbench daemon did not become ready.')


def remote(operation: str, *args: str) -> str:
    command = shlex.join([REMOTE_PYTHON, REMOTE_HELPER, operation, *args])
    return run('exec', '-i', INSTANCE, '-c', command, '--timeout', '30')


class Blob(ctypes.Structure):
    _fields_ = [('size', ctypes.c_ulong), ('data', ctypes.POINTER(ctypes.c_ubyte))]


def protect(data: bytes, *, decrypt=False) -> bytes:
    buffer = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    library = ctypes.WinDLL('crypt32', use_last_error=True)
    function = library.CryptUnprotectData if decrypt else library.CryptProtectData
    function.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                         ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(Blob)]
    function.restype = ctypes.c_int
    if not function(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target)):
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        free = ctypes.WinDLL('kernel32').LocalFree
        free.argtypes = [ctypes.c_void_p]
        free.restype = ctypes.c_void_p
        free(target.data)
