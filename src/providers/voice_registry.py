"""Explicit supported voice vendors; no chat-API compatibility inference."""
from .openai_realtime_voice import OpenAIRealtimeVoiceProvider
from .doubao_voice import DoubaoVoiceProvider
from .volcengine_rtc_voice import VolcengineRtcVoiceProvider
from .voice_provider import VoiceProvider

PROVIDERS: tuple[type[VoiceProvider], ...] = (OpenAIRealtimeVoiceProvider, DoubaoVoiceProvider, VolcengineRtcVoiceProvider)


def voice_provider(config: dict) -> VoiceProvider:
    for provider in PROVIDERS:
        if provider.accepts(config):
            return provider()
    raise ValueError("所选 Provider 尚无实时语音实现，请选择 Codex 登录或豆包语音 Provider。")


def provider_voice_catalog(config: dict) -> dict | None:
    for provider in PROVIDERS:
        if provider.accepts(config):
            return provider.catalog()
    return None
