"""Doubao realtime voice models and provider-specific call creation."""
from urllib.parse import urlsplit

from src.voice_settings import VoiceSettings
from .voice_provider import VoiceCall, VoiceModel, VoiceOption, VoiceProvider

# Realtime 3.0 accepts the built-in and character speaker families.
REALTIME_VOICES = tuple(VoiceOption(id, label) for id, label in (
    ("zh_female_vv_uranus_bigtts", "Vivi 2.0"),
    ("zh_female_xiaohe_uranus_bigtts", "小何 2.0"),
    ("zh_male_m191_uranus_bigtts", "云舟 2.0"),
    ("zh_male_taocheng_uranus_bigtts", "小天 2.0"),
    ("en_male_tim_uranus_bigtts", "Tim"),
    ("en_female_dacey_uranus_bigtts", "Dacey"),
    ("en_female_stokie_uranus_bigtts", "Stokie"),
))
SC2_VOICES = tuple(VoiceOption(f"saturn_zh_{gender}_{name}_tob", label)
    for gender, name, label in (
        ("female", "aojiaonvyou", "傲娇女友"), ("female", "bingjiaojiejie", "病娇姐姐"),
        ("female", "chengshujiejie", "成熟姐姐"), ("female", "keainvsheng", "可爱女生"),
        ("female", "nuanxinxuejie", "暖心学姐"), ("female", "tiexinnvyou", "贴心女友"),
        ("female", "wenrouwenya", "温柔文雅"), ("female", "wumeiyujie", "妩媚御姐"),
        ("female", "xingganyujie", "性感御姐"), ("male", "aiqilingren", "傲气凌人"),
        ("male", "aojiaogongzi", "傲娇公子"), ("male", "aojiaojingying", "傲娇精英"),
        ("male", "aomanshaoye", "傲慢少爷"), ("male", "badaoshaoye", "霸道少爷"),
        ("male", "bingjiaobailian", "病娇白莲"), ("male", "bujiqingnian", "不羁青年"),
        ("male", "chengshuzongcai", "成熟总裁"), ("male", "cixingnansang", "磁性男嗓"),
        ("male", "cujingnanyou", "醋精男友"), ("male", "fengfashaonian", "风发少年"),
        ("male", "fuheigongzi", "腹黑公子"),
    ))


class DoubaoVoiceProvider(VoiceProvider):
    protocol = "agentpark-voice-v4"
    id = "doubao-realtime"
    label = "豆包实时语音"
    server_media = True
    delegation = True
    models = (VoiceModel("1.2.6.1", "Doubao 实时语音 3.0 · 1.2.6.1", REALTIME_VOICES + SC2_VOICES),)

    @classmethod
    def accepts(cls, config: dict) -> bool:
        return (config.get("type") == "doubao"
                and urlsplit(config.get("baseUrl", "")).hostname == "openspeech.bytedance.com")

    async def create_call(self, config: dict, sdp: str | None, context: str, settings: VoiceSettings,
                          *, ice_servers: tuple[dict, ...] = ()) -> VoiceCall:
        if sdp is None:
            raise ValueError("豆包实时语音需要麦克风 WebRTC offer。")
        self.validate(settings)
        from .doubao_voice_session import DoubaoVoiceSession
        session = DoubaoVoiceSession(config, settings, context, ice_servers)
        try:
            answer = await session.start(sdp)
            return VoiceCall(answer, settings.model, self.protocol, session)
        except BaseException:
            await session.aclose()
            raise
