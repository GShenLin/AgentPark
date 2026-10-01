"""Codex OAuth WebRTC call creation; audio and client delegation use its data channel.

Wire contract: openai/codex 6b4daaf, realtime_call.rs and
realtime_websocket/methods_frameless_bidi.rs. This is the Codex V3 protocol,
not the public Realtime API. Server entitlement errors remain visible.
"""
import asyncio
import json
from dataclasses import dataclass

from src.provider_auth.credentials import resolve_provider_request_credentials
from src.providers.curl_transport import CurlHttpTransport


VOICE_MODEL = "gpt-live-1-codex"
# Codex V3 shares the V1 voice catalog (core/realtime_conversation.rs).
# API Realtime V2 voices such as marin are rejected after WebRTC call creation.
VOICE_NAME = "cove"


@dataclass(frozen=True)
class VoiceCallAnswer:
    sdp: str
    model: str = VOICE_MODEL


def voice_session(context: str) -> dict:
    return {
        "model": VOICE_MODEL,
        "instructions": (
            "你是当前 AgentPark 节点的实时语音接口，用简洁自然的中文交谈。"
            "需要查询、操作文件、执行工具、了解任务进度或停止任务时，委派给 client 后端节点。"
            "后端拥有节点的完整历史、工具和权限；你自己不能声称已经执行操作。"
            "等待后端时继续听用户说话，可以交谈；新的补充要求也委派给后端。"
            "根据后端返回的真实结果回复，不编造进度或成功。"
            "挂断通话不会自动取消已经提交的任务。以下是节点背景快照：\n" + context
        ),
        "audio": {"output": {"voice": VOICE_NAME}},
        "delegation": {"type": "client"},
    }


async def create_codex_voice_call(config: dict, sdp: str, context: str) -> VoiceCallAnswer:
    if config.get("type") != "openai" or config.get("authMode") not in {"codex", "oauth"}:
        raise ValueError("这版语音通话需要使用 ChatGPT/Codex 登录的 OpenAI Provider，例如 GPT_Official。")
    credentials = await asyncio.to_thread(resolve_provider_request_credentials, config)
    if credentials.base_url != "https://chatgpt.com/backend-api/codex":
        raise ValueError("Codex 语音通话只支持官方 ChatGPT 接口。")
    response = await CurlHttpTransport().request_async(
        url=credentials.base_url + "/realtime/calls?intent=quicksilver&architecture=avas",
        method="POST",
        headers={**credentials.headers, "Content-Type": "application/json", "openai-alpha": "quicksilver=v2"},
        body=json.dumps({"sdp": sdp, "session": voice_session(context)}, ensure_ascii=False).encode("utf-8"),
        timeout_sec=40, follow_redirects=False, max_response_bytes=256_000,
    )
    if response.status_code != 201:
        # Do not relay raw HTML, headers, or credential-bearing request diagnostics.
        detail = ""
        try:
            error = response.json().get("error")
            if isinstance(error, dict) and isinstance(error.get("message"), str):
                detail = error["message"][:600]
        except (ValueError, AttributeError):
            detail = "服务器未返回结构化错误。"
        for value in credentials.headers.values():
            if value:
                detail = detail.replace(value, "[redacted]")
        raise ValueError(f"创建语音通话失败（HTTP {response.status_code}）：{detail}")
    if not response.body.startswith("v=0") or "m=audio" not in response.body:
        raise ValueError("语音服务器未返回有效的 WebRTC 音频连接信息。")
    return VoiceCallAnswer(sdp=response.body)
