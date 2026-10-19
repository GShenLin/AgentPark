"""Screenshot-bound drawings; native overlays are prepared by the tool itself."""
from urllib.parse import urlsplit
from fastapi import HTTPException, Request
from src.desktop_annotations.contracts import AnnotationDrawing
from .execution_annotations import ExecutionAnnotationHost
from .request_access import has_owner_access, is_cloud_board_administrator


class VoiceAnnotations:
    def __init__(self, voice):
        self.voice = voice

    def apply(self, node_id: str, session_id: str, payload: AnnotationDrawing,
              request: Request, graph_id: str = 'default'):
        if not has_owner_access(request):
            raise HTTPException(403, '请登录设备所有者账号后使用桌面标注。')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '不允许跨站桌面标注。')
        origin = request.headers.get('origin')
        if origin and not is_cloud_board_administrator(request) and urlsplit(origin).netloc != request.url.netloc:
            raise HTTPException(403, '标注请求来源与当前页面不一致。')
        graph_id = self.voice.core.graph_runtime._sanitize_graph_id(graph_id)
        with self.voice._lock:
            lease = self.voice._lease(session_id, node_id, graph_id, request)
            if lease.finished is not None or lease.call is None:
                raise HTTPException(409, '语音通话已结束。')
            generation = lease.visual_generation
        try:
            with lease.visual_lock:
                with self.voice._lock:
                    if lease.finished is not None or lease.visual_generation != generation:
                        raise HTTPException(409, '语音通话已结束。')
                    if payload.action == 'clear':
                        host = lease.annotations
                        screenshot = None
                    else:
                        screenshot = lease.screenshots.get(payload.frame_id)
                        if screenshot is None:
                            raise HTTPException(409, '请先调用 capture_execution_screen 截图，并使用返回的 frame_id 标注。')
                        target = self.voice.capture.target(node_id, graph_id)
                        if screenshot.target != target:
                            raise HTTPException(409, '执行设备已变化，请重新截图后标注。')
                        host = lease.annotations
                        if host is not None and host.target != target:
                            host.close(); lease.annotations = None; host = None
                if payload.action == 'clear':
                    if host is not None:
                        host.command({'action': 'clear', 'annotation_id': host.identity})
                    return {'ok': True}
                if host is None:
                    host = ExecutionAnnotationHost(self.voice, screenshot.target)
                    with self.voice._lock:
                        if (lease.finished is not None or lease.visual_generation != generation
                                or self.voice.capture.target(node_id, graph_id) != screenshot.target):
                            host.close()
                            raise HTTPException(409, '通话或执行设备已变化，本次标注已取消。')
                        lease.annotations = host
                if screenshot.display.model_dump() not in host.displays:
                    raise HTTPException(409, '显示器布局已变化，请重新截图后标注。')
                return host.command({'action': 'draw', 'annotation_id': host.identity,
                                     'display_id': screenshot.display.id, 'drawing': payload.model_dump()})
        except (RuntimeError, OSError, ValueError, LookupError, TimeoutError) as exc:
            raise HTTPException(409, str(exc)) from exc
