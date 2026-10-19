"""One tool call captures one execution display and delivers it directly to the model."""
from dataclasses import dataclass
import logging

from fastapi import HTTPException, Request
from pydantic import Field

from src.desktop_capture.contracts import Contract, CaptureRequest, Display
from .execution_capture import ExecutionTarget
from .request_access import has_owner_access

LOGGER = logging.getLogger(__name__)


class ScreenshotCommand(Contract):
    request_id: str = Field(min_length=1, max_length=200)
    display_id: str = Field(default='', max_length=100)


@dataclass(frozen=True)
class VoiceScreenshot:
    target: ExecutionTarget
    display: Display
    width: int
    height: int
    captured_at: str


class VoiceScreenshots:
    def __init__(self, voice):
        self.voice = voice

    def apply(self, node_id: str, session_id: str, payload: ScreenshotCommand,
              request: Request, graph_id: str = 'default'):
        if not has_owner_access(request):
            raise HTTPException(403, '执行端截图仅对设备所有者开放。')
        if request.headers.get('sec-fetch-site') == 'cross-site':
            raise HTTPException(403, '不允许跨站调用截图工具。')
        graph_id = self.voice.core.graph_runtime._sanitize_graph_id(graph_id)
        with self.voice._lock:
            lease = self.voice._lease(session_id, node_id, graph_id, request)
            if lease.finished is not None or lease.call is None or lease.call.screen is None:
                raise HTTPException(409, '当前语音会话无法接收截图。')
            generation = lease.visual_generation
        try:
            with lease.visual_lock:
                def current():
                    return lease.finished is None and lease.visual_generation == generation

                if not current():
                    raise HTTPException(409, '通话已结束，本次截图已取消。')
                target = self.voice.capture.target(node_id, graph_id)
                cached = lease.screenshot_requests.get(payload.request_id)
                if cached:
                    previous_target, previous_display, result = cached
                    if (previous_target, previous_display) != (target, payload.display_id):
                        raise HTTPException(409, '同一截图请求不能改换执行设备或显示器。')
                    return result
                catalog = self.voice.capture.capture(target, CaptureRequest(action='displays'))
                selected = next((d for d in catalog.displays if d.id == payload.display_id), None) if payload.display_id else next(
                    (d for d in catalog.displays if d.primary), None)
                if selected is None:
                    raise HTTPException(400, '未找到指定显示器或主显示器。')
                frame = self.voice.capture.capture(target, CaptureRequest(action='frame', display_id=selected.id, max_chars=180000))
                if frame.display_id != selected.id:
                    raise RuntimeError('截图显示器与请求不一致。')

                with self.voice._lock:
                    if not current() or self.voice.capture.target(node_id, graph_id) != target:
                        raise HTTPException(409, '通话或执行设备已变化，本次截图已取消。')
                identity = lease.call.screen.publish(session_id, frame, current)
                with self.voice._lock:
                    if not current() or self.voice.capture.target(node_id, graph_id) != target:
                        raise HTTPException(409, '执行设备已变化，请重新截图。')
                    lease.screenshots[identity] = VoiceScreenshot(target, selected, frame.width, frame.height, frame.captured_at)
                    while len(lease.screenshots) > 20:
                        del lease.screenshots[next(iter(lease.screenshots))]
                    result = {'ok': True, 'frame_id': identity, 'delivered': True,
                              'device_name': catalog.device_name, 'display_id': selected.id,
                              'width': frame.width, 'height': frame.height, 'captured_at': frame.captured_at,
                              'displays': [d.model_dump() for d in catalog.displays],
                              'notice': '已截取一张静态画面并提交到语音服务；图像消息与这份文字回执分别传递。请结合对应图像回答，不要把读图委派给节点。没有开启屏幕共享，需要新画面时再次调用截图工具。'}
                    lease.screenshot_requests[payload.request_id] = (target, payload.display_id, result)
                    while len(lease.screenshot_requests) > 20:
                        del lease.screenshot_requests[next(iter(lease.screenshot_requests))]
                    return result
        except (RuntimeError, OSError, ValueError, LookupError, TimeoutError) as exc:
            LOGGER.warning('Execution screenshot failed for node %s: %s', node_id, exc)
            raise HTTPException(409, str(exc)) from exc
