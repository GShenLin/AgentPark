"""RTC image transport: send a single capture straight from the server to the AI bot.

Uses the official RTS binary control message, not a browser video publisher or
an OpenAI image event. The phone receives no image bytes.
"""
import base64
from collections import deque
from collections.abc import Callable
import json
import threading
import uuid

from src.desktop_capture.contracts import CapturedFrame
from .voice_screen import VoiceScreenSink


class VolcengineRtcScreen(VoiceScreenSink):
    def __init__(self, session):
        self.session = session
        self.lock = threading.Lock()
        self.closed = False
        self.group = 0
        self.groups: deque[int] = deque()

    def _send(self, image: dict, message: str = ""):
        content = json.dumps({'Command': 'ExternalTextToLLM', 'Message': message,
                              'InterruptMode': 2, 'ImageConfig': image}, separators=(',', ':')).encode()
        binary = b'ctrl' + len(content).to_bytes(4, 'big') + content
        result = self.session.api.post_json('SendRoomUnicast', '2023-07-20', {
            'AppId': self.session.identity['AppId'], 'RoomId': self.session.identity['RoomId'],
            'From': 'agentpark_voice_tools', 'To': self.session.bot, 'Binary': True,
            'Message': base64.b64encode(binary).decode('ascii'),
        })
        if result.get('Result', {}).get('Message') != 'Success':
            raise ValueError('火山 RTC 未确认接收截图消息。')

    def publish(self, session_id: str, frame: CapturedFrame, current: Callable[[], bool]) -> str:
        with self.lock:
            if self.closed or self.session.closed or not self.session.started or not current():
                raise RuntimeError('语音会话已结束，截图未发送。')
            self.group += 1
            group = self.group
            identity = 'exec_' + uuid.uuid4().hex[:24]
            data = frame.image.split(',', 1)[1]
            chunks = [data[offset:offset + 48000] for offset in range(0, len(data), 48000)]
            for number, chunk in enumerate(chunks, 1):
                if self.closed or self.session.closed or not current():
                    raise RuntimeError('通话已结束，本次截图已取消。')
                self._send({'Action': 'insert', 'GroupID': group, 'ImageType': 'base64',
                            'Images': [chunk], 'Total': len(chunks), 'ImageID': 1,
                            'IsPartial': number != len(chunks), 'FragmentID': number},
                           f'截图工具的图像输入 frame_id={identity}，尺寸 {frame.width}x{frame.height}，标注坐标为整图归一化坐标。图片已随本条消息输入；现在请直接根据这张图片回答用户刚才的问题，不要再次截图或委派。' if number == len(chunks) else '')
            self.groups.append(group)
            while len(self.groups) > 20:
                self._send({'Action': 'delete', 'GroupID': self.groups[0]})
                self.groups.popleft()
            return identity

    def close(self):
        # RTC StopVoiceChat owns the remote context lifetime. Never block hangup
        # on an in-flight image HTTP request or make a second audio stop request.
        self.closed = True
