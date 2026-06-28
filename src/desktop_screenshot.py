import ctypes
import os
from ctypes import wintypes


class ScreenshotCaptureError(RuntimeError):
    pass


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 3)]


def capture_image(region, backend):
    errors = []
    if backend in {"gdi", "auto"}:
        try:
            image, actual_region = capture_with_windows_gdi(region)
            return image, "gdi", actual_region
        except Exception as exc:
            if backend == "gdi":
                raise ScreenshotCaptureError(f"gdi capture failed: {type(exc).__name__}: {exc}") from exc
            errors.append(f"gdi={type(exc).__name__}: {exc}")

    if backend in {"pyautogui", "auto"}:
        try:
            image, actual_region = capture_with_pyautogui(region)
            return image, "pyautogui", actual_region
        except Exception as exc:
            errors.append(f"pyautogui={type(exc).__name__}: {exc}")

    raise ScreenshotCaptureError("capture failed: " + "; ".join(errors))


def capture_with_pyautogui(region):
    import pyautogui  # type: ignore

    actual_region = _copy_region(region)
    region_tuple = None
    if actual_region is not None:
        region_tuple = (
            actual_region["left"],
            actual_region["top"],
            actual_region["width"],
            actual_region["height"],
        )
    image = pyautogui.screenshot(region=region_tuple)
    if actual_region is None:
        width, height = image.size
        actual_region = {"left": 0, "top": 0, "width": int(width), "height": int(height)}
    return image, actual_region


def capture_with_windows_gdi(region):
    if os.name != "nt":
        raise ScreenshotCaptureError("Windows GDI capture is only available on Windows.")

    from PIL import Image  # type: ignore

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
    _configure_win32_signatures(user32, gdi32)

    actual_region = _resolve_gdi_region(user32, region)
    left = int(actual_region["left"])
    top = int(actual_region["top"])
    width = int(actual_region["width"])
    height = int(actual_region["height"])

    hdc_screen = user32.GetDC(None)
    if not hdc_screen:
        raise ctypes.WinError(ctypes.get_last_error())
    hdc_mem = None
    bitmap = None
    old_bitmap = None
    try:
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        if not hdc_mem:
            raise ctypes.WinError(ctypes.get_last_error())
        bitmap = gdi32.CreateCompatibleBitmap(hdc_screen, width, height)
        if not bitmap:
            raise ctypes.WinError(ctypes.get_last_error())
        old_bitmap = gdi32.SelectObject(hdc_mem, bitmap)
        if not old_bitmap:
            raise ctypes.WinError(ctypes.get_last_error())

        srccopy = 0x00CC0020
        captureblt = 0x40000000
        if not gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, srccopy | captureblt):
            raise ctypes.WinError(ctypes.get_last_error())

        bitmap_info = BITMAPINFO()
        bitmap_info.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bitmap_info.bmiHeader.biWidth = width
        bitmap_info.bmiHeader.biHeight = -height
        bitmap_info.bmiHeader.biPlanes = 1
        bitmap_info.bmiHeader.biBitCount = 32
        bitmap_info.bmiHeader.biCompression = 0

        buffer = ctypes.create_string_buffer(width * height * 4)
        lines = gdi32.GetDIBits(hdc_mem, bitmap, 0, height, buffer, ctypes.byref(bitmap_info), 0)
        if lines != height:
            raise ctypes.WinError(ctypes.get_last_error())

        return Image.frombuffer("RGB", (width, height), buffer, "raw", "BGRX", 0, 1).copy(), actual_region
    finally:
        if hdc_mem and old_bitmap:
            gdi32.SelectObject(hdc_mem, old_bitmap)
        if bitmap:
            gdi32.DeleteObject(bitmap)
        if hdc_mem:
            gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(None, hdc_screen)


def _copy_region(region):
    if region is None:
        return None
    return {
        "left": int(region["left"]),
        "top": int(region["top"]),
        "width": int(region["width"]),
        "height": int(region["height"]),
    }


def _resolve_gdi_region(user32, region):
    copied = _copy_region(region)
    if copied is not None:
        return copied

    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)
    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)
    if width <= 0 or height <= 0:
        left = 0
        top = 0
        width = user32.GetSystemMetrics(0)
        height = user32.GetSystemMetrics(1)
    if width <= 0 or height <= 0:
        raise ScreenshotCaptureError("failed to resolve screen dimensions.")
    return {"left": int(left), "top": int(top), "width": int(width), "height": int(height)}


def _configure_win32_signatures(user32, gdi32):
    user32.GetDC.argtypes = [wintypes.HWND]
    user32.GetDC.restype = wintypes.HDC
    user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
    user32.ReleaseDC.restype = ctypes.c_int
    user32.GetSystemMetrics.argtypes = [ctypes.c_int]
    user32.GetSystemMetrics.restype = ctypes.c_int

    gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
    gdi32.CreateCompatibleDC.restype = wintypes.HDC
    gdi32.CreateCompatibleBitmap.argtypes = [wintypes.HDC, ctypes.c_int, ctypes.c_int]
    gdi32.CreateCompatibleBitmap.restype = wintypes.HANDLE
    gdi32.SelectObject.argtypes = [wintypes.HDC, wintypes.HANDLE]
    gdi32.SelectObject.restype = wintypes.HANDLE
    gdi32.BitBlt.argtypes = [
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HDC,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.DWORD,
    ]
    gdi32.BitBlt.restype = wintypes.BOOL
    gdi32.GetDIBits.argtypes = [
        wintypes.HDC,
        wintypes.HANDLE,
        wintypes.UINT,
        wintypes.UINT,
        ctypes.c_void_p,
        ctypes.POINTER(BITMAPINFO),
        wintypes.UINT,
    ]
    gdi32.GetDIBits.restype = ctypes.c_int
    gdi32.DeleteObject.argtypes = [wintypes.HANDLE]
    gdi32.DeleteObject.restype = wintypes.BOOL
    gdi32.DeleteDC.argtypes = [wintypes.HDC]
    gdi32.DeleteDC.restype = wintypes.BOOL
