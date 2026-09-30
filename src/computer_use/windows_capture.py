"""Capture an exact HWND through Windows Graphics Capture, without title matching."""
import threading
import time

from src.runtime_cancellation import raise_if_cancel_requested
from .contracts import ComputerUseError


def capture_window(hwnd, cancel, timeout=8):
    from PIL import Image
    from windows_capture import WindowsCapture

    done = threading.Event()
    result = {}
    capture = WindowsCapture(window_hwnd=hwnd, cursor_capture=False)

    @capture.event
    def on_frame_arrived(frame, control):
        try:
            result['image'] = Image.fromarray(frame.frame_buffer[:, :, [2, 1, 0]].copy())
        except Exception as exc:
            result['error'] = exc
        finally:
            control.stop()
            done.set()

    @capture.event
    def on_closed():
        done.set()

    try:
        control = capture.start_free_threaded()
    except Exception as exc:
        raise ComputerUseError(
            f'WGC cannot capture window id={hwnd}: {exc}. '
            'For a visible popup/tool window, request get_window_state with '
            'capture_mode="visible_region" to inspect its on-screen rectangle.') from exc
    try:
        deadline = time.monotonic() + timeout
        while not done.wait(0.05):
            raise_if_cancel_requested(cancel)
            if time.monotonic() >= deadline:
                raise ComputerUseError('Window capture timed out; verify the window is not minimized.')
        raise_if_cancel_requested(cancel)
        if 'error' in result:
            raise ComputerUseError(f"Window capture failed: {result['error']}") from result['error']
        if 'image' not in result:
            raise ComputerUseError('Window closed before a frame was captured.')
        return result['image']
    finally:
        if not control.is_finished():
            control.stop()
