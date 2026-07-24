"""Agent SupportMode contracts.

SupportMode is the stable provider-facing capability boundary.  Individual
audio protocols are selected through ``audio_operation`` inside the single
``audio_generation`` mode; they are not separate provider support modes.
"""
from __future__ import annotations

from collections.abc import Mapping


MODE_CHAT = "chat"
MODE_IMAGE_GENERATION = "image_generation"
MODE_VIDEO_GENERATION = "video_generation"
MODE_AUDIO_GENERATION = "audio_generation"
MODE_IMAGE_CHAT = "imagechat"
MODE_VISION_UNDERSTAND = "vision_understand"
MODE_GUI_AGENT = "guiagent"

MODE_ORDER = (
    MODE_CHAT,
    MODE_IMAGE_GENERATION,
    MODE_VIDEO_GENERATION,
    MODE_AUDIO_GENERATION,
    MODE_IMAGE_CHAT,
    MODE_VISION_UNDERSTAND,
    MODE_GUI_AGENT,
)

MODE_LABELS = {
    MODE_CHAT: "Chat",
    MODE_IMAGE_GENERATION: "Image Generation",
    MODE_VIDEO_GENERATION: "Video Generation",
    MODE_AUDIO_GENERATION: "Audio Generation",
    MODE_IMAGE_CHAT: "Image Chat",
    MODE_VISION_UNDERSTAND: "Vision Understand",
    MODE_GUI_AGENT: "GUI Agent",
}

COMMON_FIELDS = frozenset({
    "provider_id",
    "instruction",
    "system_prompt",
})

CHAT_FIELDS = frozenset({
    "collaboration_mode",
    "plugins",
    "tools",
    "mcp_servers",
    "skills",
    "web_search",
    "thinking",
    "reasoning_effort",
    "reasoning_summary",
})

IMAGE_FIELDS = frozenset({
    "image_references",
    "image_size",
    "image_aspect_ratio",
    "image_optimize_prompt_mode",
    "image_output_format",
    "image_response_format",
    "image_sequential_image_generation",
    "image_max_images",
    "image_stream",
    "image_tools",
    "image_watermark",
    "image_filename_prefix",
})

VIDEO_FIELDS = frozenset({
    "video_resolution",
    "video_ratio",
    "video_duration",
    "video_frames",
    "video_seed",
    "video_camera_fixed",
    "video_watermark",
    "video_generate_audio",
    "video_return_last_frame",
    "video_filename_prefix",
    "web_search",
})

AUDIO_FIELDS = frozenset({
    "audio_operation",
    "audio_model",
    "audio_speaker",
    "tts_model",
    "tts_speaker",
    "tts_resource_id",
    "tts_format",
    "tts_sample_rate",
    "tts_bit_rate",
    "tts_speech_rate",
    "tts_loudness_rate",
    "tts_pitch",
    "tts_enable_subtitle",
    "tts_aigc_watermark",
    "tts_metadata_watermark",
    "tts_ssml",
    "tts_additions",
    "tts_context_texts",
    "tts_section_id",
    "tts_tone_fidelity",
    "tts_async_resource_id",
    "tts_async_poll_interval_seconds",
    "tts_async_poll_timeout_seconds",
    "asr_source_audio",
    "asr_resource_id",
    "asr_uid",
    "asr_model_name",
    "asr_enable_itn",
    "asr_enable_punc",
    "asr_enable_ddc",
    "asr_enable_speaker_info",
    "asr_standard_resource_id",
    "asr_idle_resource_id",
    "asr_language",
    "asr_audio_format",
    "asr_audio_codec",
    "asr_audio_rate",
    "asr_audio_bits",
    "asr_audio_channel",
    "asr_show_utterances",
    "asr_enable_channel_split",
    "asr_poll_interval_seconds",
    "asr_poll_timeout_seconds",
    "asr_stream_resource_id",
    "asr_stream_endpoint_mode",
    "asr_stream_chunk_ms",
    "translation_source_language",
    "translation_target_language",
    "translation_text_list",
    "translation_corpus",
    "translation_resource_id",
    "minutes_source_url",
    "minutes_file_type",
    "minutes_source_language",
    "minutes_all_activate",
    "minutes_speaker_identification",
    "minutes_number_of_speakers",
    "minutes_hot_words",
    "minutes_need_word_time_series",
    "minutes_translation_enabled",
    "minutes_target_language",
    "minutes_information_types",
    "minutes_summarization_enabled",
    "minutes_chapter_enabled",
    "minutes_resource_id",
    "minutes_poll_interval_seconds",
    "minutes_poll_timeout_seconds",
    "podcast_action",
    "podcast_input_text",
    "podcast_input_url",
    "podcast_prompt_text",
    "podcast_nlp_texts",
    "podcast_speakers",
    "podcast_random_speaker_order",
    "podcast_format",
    "podcast_sample_rate",
    "podcast_speech_rate",
    "podcast_use_head_music",
    "podcast_use_tail_music",
    "podcast_return_audio_url",
    "podcast_strict_audit",
    "podcast_input_text_max_length",
    "podcast_resource_id",
    "realtime_input_mode",
    "realtime_source_audio",
    "realtime_text",
    "realtime_model",
    "realtime_speaker",
    "realtime_bot_name",
    "realtime_system_role",
    "realtime_speaking_style",
    "realtime_character_manifest",
    "realtime_strict_audit",
    "realtime_speech_rate",
    "realtime_loudness_rate",
    "realtime_resource_id",
    "realtime_chunk_ms",
    "simultrans_source_audio",
    "simultrans_mode",
    "simultrans_source_language",
    "simultrans_target_language",
    "simultrans_speaker",
    "simultrans_target_format",
    "simultrans_target_rate",
    "simultrans_hot_words",
    "simultrans_glossary",
    "simultrans_boosting_table_id",
    "simultrans_boosting_table_name",
    "simultrans_correct_table_id",
    "simultrans_correct_table_name",
    "simultrans_denoise",
    "simultrans_enable_speaker_info",
    "simultrans_resource_id",
    "simultrans_chunk_ms",
    "audio_references",
    "audio_format",
    "audio_sample_rate",
    "audio_speech_rate",
    "audio_loudness_rate",
    "audio_pitch_rate",
    "audio_enable_subtitle",
    "audio_aigc_watermark",
    "audio_metadata_watermark",
    "audio_filename_prefix",
})

MODE_FIELDS = {
    MODE_CHAT: COMMON_FIELDS | CHAT_FIELDS,
    MODE_IMAGE_GENERATION: COMMON_FIELDS | IMAGE_FIELDS,
    MODE_VIDEO_GENERATION: COMMON_FIELDS | VIDEO_FIELDS,
    MODE_AUDIO_GENERATION: COMMON_FIELDS | AUDIO_FIELDS,
    MODE_IMAGE_CHAT: COMMON_FIELDS | CHAT_FIELDS,
    MODE_VISION_UNDERSTAND: COMMON_FIELDS,
    MODE_GUI_AGENT: COMMON_FIELDS | CHAT_FIELDS,
}


def modes_for_field(field_name: str) -> tuple[str, ...]:
    """Return all SupportModes that own a schema field."""
    key = str(field_name or "").strip()
    if key in COMMON_FIELDS:
        return ()
    return tuple(mode for mode in MODE_ORDER if key in MODE_FIELDS.get(mode, ()))


def capability_mode(mode: object) -> bool:
    return str(mode or "").strip().lower() in {MODE_CHAT, MODE_IMAGE_CHAT, MODE_GUI_AGENT}


def resolve_input_support_mode(support_modes: object, message: object) -> str:
    """Resolve one execution mode without storing a node-level current mode."""
    modes = tuple(
        str(item or "").strip().lower()
        for item in support_modes
        if str(item or "").strip().lower() in MODE_FIELDS
    ) if isinstance(support_modes, (list, tuple)) else ()
    if not modes:
        raise ValueError("Selected provider does not declare an Agent SupportMode.")

    explicit = ""
    parts = message.get("parts") if isinstance(message, Mapping) else None
    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, Mapping) or str(part.get("type") or "").strip().lower() != "meta":
            continue
        meta = part.get("meta")
        if isinstance(meta, Mapping) and str(meta.get("support_mode") or "").strip():
            explicit = str(meta.get("support_mode") or "").strip().lower()
            break
    if explicit:
        if explicit not in modes:
            raise ValueError(f"Provider does not declare requested SupportMode '{explicit}'.")
        return explicit
    if len(modes) == 1:
        return modes[0]
    if MODE_IMAGE_CHAT in modes:
        return MODE_IMAGE_CHAT
    if MODE_CHAT in modes:
        return MODE_CHAT
    raise ValueError(
        "Provider declares multiple non-chat SupportModes; the input must include meta.support_mode."
    )


def settings_for_mode(
    mode: object,
    config: Mapping[str, object] | None,
    context: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Copy only settings owned by the selected SupportMode."""
    resolved_mode = str(mode or MODE_CHAT).strip().lower() or MODE_CHAT
    allowed = MODE_FIELDS.get(resolved_mode, COMMON_FIELDS) - COMMON_FIELDS
    stored = config if isinstance(config, Mapping) else {}
    fallback = context if isinstance(context, Mapping) else {}
    output: dict[str, object] = {}
    for key in allowed:
        if key in stored:
            output[key] = stored[key]
        elif key in fallback:
            output[key] = fallback[key]
    return output
