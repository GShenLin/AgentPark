"""One bounded Windows capture per request; no background recorder or disk images."""
import base64
from contextlib import contextmanager
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import io
import os
import socket

from .contracts import CaptureRequest, CapturedFrame, Display, DisplayCatalog


@contextmanager
def physical_pixels():
    if os.name != 'nt':
        raise RuntimeError('执行设备的截图目前支持 Windows；此设备不是 Windows。')
    user = ctypes.WinDLL('user32', use_last_error=True)
    user.SetThreadDpiAwarenessContext.argtypes = [ctypes.c_void_p]
    user.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
    previous = user.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    if not previous:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        yield user
    finally:
        if not user.SetThreadDpiAwarenessContext(previous):
            raise ctypes.WinError(ctypes.get_last_error())


def displays() -> DisplayCatalog:
    class MonitorInfo(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('monitor', wintypes.RECT),
                    ('work', wintypes.RECT), ('flags', wintypes.DWORD), ('device', wintypes.WCHAR * 32)]

    result, errors = [], []
    callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HANDLE, wintypes.HDC,
                                       ctypes.POINTER(wintypes.RECT), wintypes.LPARAM) if os.name == 'nt' else None
    with physical_pixels() as user:
        user.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.POINTER(MonitorInfo)]
        user.GetMonitorInfoW.restype = wintypes.BOOL
        user.EnumDisplayMonitors.argtypes = [wintypes.HDC, ctypes.c_void_p, callback_type, wintypes.LPARAM]
        user.EnumDisplayMonitors.restype = wintypes.BOOL

        @callback_type
        def collect(handle, _dc, _rect, _data):
            info = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
            if not user.GetMonitorInfoW(handle, ctypes.byref(info)):
                errors.append(ctypes.get_last_error())
                return False
            bounds = info.monitor
            geometry = (bounds.left, bounds.top, bounds.right - bounds.left, bounds.bottom - bounds.top)
            # A display move/resize invalidates selection instead of capturing a different rectangle.
            identity = hashlib.sha256(f'{info.device}:{geometry}'.encode()).hexdigest()[:32]
            primary = bool(info.flags & 1)
            result.append(Display(id=identity, label=f'{info.device} · {geometry[2]}×{geometry[3]}' + (' · 主屏幕' if primary else ''),
                                  x=geometry[0], y=geometry[1], width=geometry[2], height=geometry[3], primary=primary))
            return True

        if not user.EnumDisplayMonitors(None, None, collect, 0):
            raise ctypes.WinError(errors[0] if errors else ctypes.get_last_error())
    if not result:
        raise RuntimeError('执行设备没有可截图的交互式桌面显示器。')
    return DisplayCatalog(device_name=socket.gethostname(), displays=result)


def encode_frame(image, display_id: str, max_chars: int) -> CapturedFrame:
    from PIL import Image
    image = image.convert('RGB')
    image.thumbnail((1600, 1600), Image.Resampling.LANCZOS)
    def encoded(candidate):
        output = io.BytesIO()
        candidate.save(output, format='JPEG', quality=65)
        return 'data:image/jpeg;base64,' + base64.b64encode(output.getvalue()).decode('ascii')

    # Fixed JPEG quality; binary-search spatial resolution against the negotiated
    # message budget. Never truncate a JPEG or exceed the data channel contract.
    url = encoded(image)
    best = (image, url) if len(url) <= max_chars else None
    low, high = min(640, max(image.size)), max(image.size) - 1
    if best is not None:
        high = low - 1
    while low <= high:
        edge = (low + high) // 2
        candidate = image.copy()
        candidate.thumbnail((edge, edge), Image.Resampling.LANCZOS)
        candidate_url = encoded(candidate)
        if len(candidate_url) <= max_chars:
            best = (candidate, candidate_url)
            low = edge + 1
        else:
            high = edge - 1
    if best is None:
        raise RuntimeError('执行端画面超出语音传输大小限制，请选择分辨率较小的显示器。')
    selected, url = best
    return CapturedFrame(display_id=display_id, captured_at=datetime.now(timezone.utc).isoformat(),
                         width=selected.width, height=selected.height, image=url)


def execute_capture(request: CaptureRequest) -> DisplayCatalog | CapturedFrame:
    catalog = displays()
    if request.action == 'displays':
        return catalog
    selected = next((display for display in catalog.displays if display.id == request.display_id), None)
    if selected is None:
        raise ValueError('显示器已断开或布局已变化，请重新选择截图。')
    from PIL import ImageGrab
    with physical_pixels():
        image = ImageGrab.grab(bbox=(selected.x, selected.y, selected.x + selected.width, selected.y + selected.height), all_screens=True)
    if selected not in displays().displays:
        raise ValueError('采集期间显示器布局已变化，画面已丢弃。')
    return encode_frame(image, selected.id, request.max_chars)
