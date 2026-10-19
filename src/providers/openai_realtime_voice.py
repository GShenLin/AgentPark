"""OpenAI Realtime GA WebRTC. Credentials stay on the trusted server."""
import asyncio
import json
import uuid

from src.provider_auth.credentials import resolve_provider_request_credentials
from src.providers.curl_transport import CurlHttpTransport
from src.voice_settings import VOICE_MODEL, VoiceSettings, supports_openai_voice, voice_catalog
from .voice_provider import VoiceCall, VoiceModel, VoiceOption, VoiceProvider
from .openai_realtime_screen import OpenAIRealtimeScreen


def voice_session(context: str, settings: VoiceSettings) -> dict:
    return {
        "type": "realtime", "model": settings.model,
        "instructions": VoiceProvider.instructions(context),
        "output_modalities": ["audio"],
        "audio": {
            "input": {
                "transcription": {"model": "gpt-4o-mini-transcribe", "language": "zh"},
                "turn_detection": {"type": "server_vad", "create_response": True,
                                   "interrupt_response": True, "silence_duration_ms": 650},
            },
            "output": {"voice": settings.voice},
        },
        "tools": VoiceProvider.tools(),
        "tool_choice": "auto",
    }


class OpenAIRealtimeVoiceProvider(VoiceProvider):
    protocol = "openai-realtime-v4"
    id = "openai-realtime"
    label = "OpenAI Realtime 语音与截图工具"
    delegation = True
    models = (VoiceModel(VOICE_MODEL, VOICE_MODEL, tuple(
        VoiceOption(item["id"], item["label"]) for item in voice_catalog())),)

    @classmethod
    def accepts(cls, config: dict) -> bool:
        return supports_openai_voice(config)

    async def create_call(self, config: dict, sdp: str | None, context: str, settings: VoiceSettings,
                          *, ice_servers: tuple[dict, ...] = ()) -> VoiceCall:
        if sdp is None:
            raise ValueError("OpenAI Realtime 需要麦克风 WebRTC offer。")
        if not self.accepts(config):
            raise ValueError("请选择已通过 ChatGPT/Codex 登录的 OpenAI 语音 Provider。")
        self.validate(settings)
        credentials = await asyncio.to_thread(resolve_provider_request_credentials, config)
        if credentials.base_url != "https://chatgpt.com/backend-api/codex":
            raise ValueError("Realtime 登录授权必须来自官方 OpenAI Provider。")
        boundary = "agentpark-realtime-" + uuid.uuid4().hex
        parts = []
        for name, mime, value in (("sdp", "application/sdp", sdp),
                                  ("session", "application/json", json.dumps(voice_session(context, settings), ensure_ascii=False))):
            parts.append(f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\nContent-Type: {mime}\r\n\r\n{value}\r\n')
        response = await CurlHttpTransport().request_async(
            url="https://api.openai.com/v1/realtime/calls", method="POST",
            headers={"Authorization": credentials.headers["Authorization"],
                     "Content-Type": f"multipart/form-data; boundary={boundary}"},
            body=("".join(parts) + f"--{boundary}--\r\n").encode("utf-8"),
            timeout_sec=40, follow_redirects=False, max_response_bytes=256_000,
        )
        if response.status_code != 201:
            detail = "服务器未返回结构化错误。"
            try:
                error = response.json().get("error")
                if isinstance(error, dict) and isinstance(error.get("message"), str):
                    detail = error["message"][:600]
            except (ValueError, AttributeError):
                pass  # Preserve HTTP failure even when its body is HTML.
            for value in credentials.headers.values():
                if value:
                    detail = detail.replace(value, "[redacted]").replace(value.removeprefix("Bearer "), "[redacted]")
            raise ValueError(f"创建 Realtime 通话失败（HTTP {response.status_code}）：{detail}")
        if not response.body.startswith("v=0") or "m=audio" not in response.body:
            raise ValueError("Realtime 未返回有效的 WebRTC 音频连接信息。")
        return VoiceCall(sdp=response.body, model=settings.model, protocol=self.protocol,
                         screen=OpenAIRealtimeScreen(response.headers.get('location', ''), credentials.headers['Authorization']))
