"""Explicit visual voice provider: RTC + ASR + vision LLM + TTS."""
import asyncio
import re
import uuid
from urllib.parse import urlsplit

from .voice_provider import RtcVoiceCall, VoiceModel, VoiceOption, VoiceProvider
from .volcengine_openapi import VolcengineOpenApi
from .volcengine_rtc_token import rtc_token
from .volcengine_rtc_session import VolcengineRtcSession


class VolcengineRtcVoiceProvider(VoiceProvider):
    id = "volcengine-rtc"
    label = "火山视觉语音 · RTC"
    protocol = "volcengine-rtc-v1"
    transport = "volcengine-rtc"
    delegation = True
    models = (VoiceModel("doubao-seed-2-0-lite-260428", "豆包 Seed 2.0 Lite · 视觉语音", (
        VoiceOption("zh_female_vv_uranus_bigtts", "Vivi 2.0"),
        VoiceOption("zh_female_xiaohe_uranus_bigtts", "小何 2.0"),
        VoiceOption("zh_male_m191_uranus_bigtts", "云舟 2.0"),
        VoiceOption("zh_male_taocheng_uranus_bigtts", "小天 2.0"),
    )),)

    @classmethod
    def accepts(cls, config: dict) -> bool:
        return (config.get("type") == "doubao"
                and urlsplit(config.get("baseUrl", "")).hostname == "rtc.volcengineapi.com")

    async def create_call(self, config, sdp, context, settings, *, ice_servers=()) -> RtcVoiceCall:
        self.validate(settings)
        if sdp is not None:
            raise ValueError("火山 RTC 通过 SDK 入房，不接受 SDP offer。")
        app_id = config.get("rtcAppId", "")
        if not isinstance(app_id, str) or not re.fullmatch(r"[a-f0-9]{24}", app_id):
            raise ValueError("请在火山 RTC Provider 中配置 AI 音视频应用 AppId。")
        api = VolcengineOpenApi(access_key_id=config.get("speechAccessKeyId"),
                               secret_access_key=config.get("speechSecretAccessKey"),
                               service="rtc", domain="rtc.volcengineapi.com", timeout=25)
        response = await asyncio.to_thread(api.post_json, "ListApps", "2020-12-01", {})
        apps = response.get("Result", {}).get("AppList")
        if not isinstance(apps, list):
            raise ValueError("火山 ListApps 返回格式错误。")
        app = next((item for item in apps if item.get("AppId") == app_id), None)
        if app is None or app.get("Status") != 1 or not isinstance(app.get("AppKey"), str) or not app["AppKey"]:
            raise ValueError("当前凭据无法取得所选 RTC 应用密钥，或应用未启用。")
        room, user, bot = "ap_" + uuid.uuid4().hex, "user_" + uuid.uuid4().hex, "bot_" + uuid.uuid4().hex
        session = VolcengineRtcSession(api, app_id, room, user, bot, context, settings)
        return RtcVoiceCall(app_id, room, user, bot, rtc_token(app_id, app["AppKey"], room, user),
                            settings.model, session)
