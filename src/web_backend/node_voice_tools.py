"""Call-owned immediate tool feedback shared by all server voice transports."""
from fastapi import HTTPException, Request

from src.providers.voice_tools import VoiceToolResult


class VoiceToolFeedback:
    def __init__(self, voice):
        self.voice = voice

    async def deliver(self, node_id: str, session_id: str, call_id: str,
                      payload: VoiceToolResult, request: Request, graph_id: str = 'default'):
        graph_id = self.voice.core.graph_runtime._sanitize_graph_id(graph_id)
        with self.voice._lock:
            lease = self.voice._lease(session_id, node_id, graph_id, request)
            if lease.finished is not None or lease.call is None:
                raise HTTPException(409, '语音通话已结束。')
            if not call_id or len(call_id) > 200:
                raise HTTPException(400, '工具调用编号无效。')
            if call_id in lease.tasks:
                raise HTTPException(400, '后台任务状态必须从节点执行记录回传。')
            if payload.image_frame_id is not None and payload.image_frame_id not in lease.screenshots:
                raise HTTPException(400, '图片结果不属于当前通话的截图。')
            session = lease.call.session
            if session is None:
                raise HTTPException(400, '当前通话通过数据通道返回工具结果。')
        try:
            delivery = await session.deliver_tool_result(call_id, payload)
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(400, str(exc)) from exc
        return {'delivery': delivery}
