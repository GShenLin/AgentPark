"""Operation dispatcher for the audio_generation SupportMode."""
from __future__ import annotations

from src.service_host import HostBoundService


_OPERATION_FIELDS = {
    "generate": {
        "audio_model", "audio_speaker", "audio_references", "audio_format",
        "audio_sample_rate", "audio_speech_rate", "audio_loudness_rate",
        "audio_pitch_rate", "audio_enable_subtitle", "audio_aigc_watermark",
        "audio_metadata_watermark", "audio_filename_prefix",
    },
    "tts_http": {
        "tts_model", "tts_speaker", "tts_resource_id", "tts_format",
        "tts_sample_rate", "tts_bit_rate", "tts_speech_rate", "tts_loudness_rate",
        "tts_pitch", "tts_enable_subtitle", "tts_aigc_watermark",
        "tts_metadata_watermark", "audio_filename_prefix", "tts_ssml",
        "tts_additions", "tts_context_texts", "tts_section_id", "tts_tone_fidelity",
    },
    "tts_async": {
        "tts_model", "tts_speaker", "tts_format", "tts_sample_rate", "tts_bit_rate",
        "tts_speech_rate", "tts_loudness_rate", "tts_enable_subtitle", "tts_additions",
        "tts_async_resource_id", "tts_async_poll_interval_seconds", "tts_async_poll_timeout_seconds",
        "audio_filename_prefix",
    },
    "tts_ws_unidirectional": {
        "tts_model", "tts_speaker", "tts_resource_id", "tts_format", "tts_sample_rate",
        "tts_bit_rate", "tts_speech_rate", "tts_loudness_rate", "tts_pitch",
        "tts_enable_subtitle", "tts_aigc_watermark", "tts_metadata_watermark",
        "tts_ssml", "tts_additions", "tts_context_texts", "tts_section_id",
        "tts_tone_fidelity", "audio_filename_prefix",
    },
    "tts_ws_bidirectional": {
        "tts_model", "tts_speaker", "tts_resource_id", "tts_format", "tts_sample_rate",
        "tts_bit_rate", "tts_speech_rate", "tts_loudness_rate", "tts_pitch",
        "tts_enable_subtitle", "tts_aigc_watermark", "tts_metadata_watermark",
        "tts_additions", "tts_context_texts", "tts_section_id", "audio_filename_prefix",
    },
    "asr_flash": {
        "asr_source_audio", "asr_resource_id", "asr_uid", "asr_model_name",
        "asr_enable_itn", "asr_enable_punc", "asr_enable_ddc", "asr_enable_speaker_info",
    },
    "asr_standard": {
        "asr_source_audio", "asr_standard_resource_id", "asr_uid", "asr_model_name",
        "asr_language", "asr_audio_format", "asr_audio_codec", "asr_audio_rate",
        "asr_audio_bits", "asr_audio_channel", "asr_enable_itn", "asr_enable_punc",
        "asr_enable_ddc", "asr_enable_speaker_info", "asr_show_utterances",
        "asr_enable_channel_split", "asr_poll_interval_seconds", "asr_poll_timeout_seconds",
    },
    "asr_idle": {
        "asr_source_audio", "asr_idle_resource_id", "asr_uid", "asr_model_name",
        "asr_language", "asr_audio_format", "asr_audio_codec", "asr_audio_rate",
        "asr_audio_bits", "asr_audio_channel", "asr_enable_itn", "asr_enable_punc",
        "asr_enable_ddc", "asr_enable_speaker_info", "asr_show_utterances",
        "asr_enable_channel_split", "asr_poll_interval_seconds", "asr_poll_timeout_seconds",
    },
    "asr_stream": {
        "asr_source_audio", "asr_stream_resource_id", "asr_stream_endpoint_mode",
        "asr_stream_chunk_ms", "asr_uid", "asr_model_name", "asr_enable_itn",
        "asr_enable_punc", "asr_enable_ddc", "asr_enable_speaker_info",
    },
    "translate": {
        "translation_source_language", "translation_target_language", "translation_text_list",
        "translation_corpus", "translation_resource_id",
    },
    "minutes": {
        "minutes_source_url", "minutes_file_type", "minutes_source_language",
        "minutes_all_activate", "minutes_speaker_identification", "minutes_number_of_speakers",
        "minutes_hot_words", "minutes_need_word_time_series", "minutes_translation_enabled",
        "minutes_target_language", "minutes_information_types", "minutes_summarization_enabled",
        "minutes_chapter_enabled", "minutes_resource_id", "minutes_poll_interval_seconds",
        "minutes_poll_timeout_seconds",
    },
    "podcast": {
        "podcast_action", "podcast_input_text", "podcast_input_url", "podcast_prompt_text",
        "podcast_nlp_texts", "podcast_speakers", "podcast_random_speaker_order",
        "podcast_format", "podcast_sample_rate", "podcast_speech_rate",
        "podcast_use_head_music", "podcast_use_tail_music", "podcast_return_audio_url",
        "podcast_strict_audit", "podcast_input_text_max_length", "podcast_resource_id",
        "audio_filename_prefix",
    },
    "realtime": {
        "realtime_input_mode", "realtime_source_audio", "realtime_text", "realtime_model",
        "realtime_speaker", "realtime_bot_name", "realtime_system_role",
        "realtime_speaking_style", "realtime_character_manifest", "realtime_strict_audit",
        "realtime_speech_rate", "realtime_loudness_rate", "realtime_resource_id",
        "realtime_chunk_ms", "audio_filename_prefix",
    },
    "simultrans": {
        "simultrans_source_audio", "simultrans_mode", "simultrans_source_language",
        "simultrans_target_language", "simultrans_speaker", "simultrans_target_format",
        "simultrans_target_rate", "simultrans_hot_words", "simultrans_glossary",
        "simultrans_boosting_table_id", "simultrans_boosting_table_name",
        "simultrans_correct_table_id", "simultrans_correct_table_name", "simultrans_denoise",
        "simultrans_enable_speaker_info", "simultrans_resource_id", "simultrans_chunk_ms",
        "audio_filename_prefix",
    },
}


class DoubaoAudioRuntime(HostBoundService):
    def run_audio_operation(self, messages: object, options: object) -> dict:
        values = dict(options or {}) if isinstance(options, dict) else {}
        operation = str(values.pop("audio_operation", "generate") or "generate").strip().lower()
        allowed = _OPERATION_FIELDS.get(operation)
        if allowed is None:
            raise ValueError(f"Unsupported audio_generation operation: {operation}")
        kwargs = {key: value for key, value in values.items() if key in allowed}
        if operation == "generate":
            return self.generate_audio(messages, **kwargs)
        if operation == "tts_http":
            return self.synthesize_tts_http(messages, **kwargs)
        if operation == "tts_async":
            return self.synthesize_tts_async(messages, **kwargs)
        if operation in {"tts_ws_unidirectional", "tts_ws_bidirectional"}:
            return self.synthesize_tts_websocket(messages, operation=operation, **kwargs)
        if operation == "asr_flash":
            return self.recognize_asr_flash(messages, **kwargs)
        if operation in {"asr_standard", "asr_idle"}:
            return self.recognize_asr_file(messages, operation=operation, **kwargs)
        if operation == "asr_stream":
            return self.recognize_asr_stream(messages, **kwargs)
        if operation == "translate":
            return self.translate_text(messages, **kwargs)
        if operation == "minutes":
            return self.generate_minutes(messages, **kwargs)
        if operation == "podcast":
            return self.generate_podcast(messages, **kwargs)
        if operation == "realtime":
            return self.run_realtime_dialogue(messages, **kwargs)
        if operation == "simultrans":
            return self.run_simultaneous_interpretation(messages, **kwargs)
        raise AssertionError(f"Unreachable audio operation: {operation}")
