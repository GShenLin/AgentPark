"""Doubao section 5 simultaneous interpretation protobuf runtime."""
from __future__ import annotations

import json
import os
import uuid
import wave
from datetime import datetime

from src.media_stream_protocol import build_audio_stream_chunk, build_audio_stream_end, build_audio_stream_start
from src.node_stream_protocol import build_node_message_delta
from src.providers.doubao_ast_proto import doubao_ast_pb2 as ast
from src.providers.provider_pressure import acquire_provider_pressure
from src.runtime_cancellation import raise_if_cancel_requested, sleep_with_cancel
from src.service_host import HostBoundService
from src.providers.doubao_speech_auth import resolve_doubao_x_api_key
from src.value_parsing import parse_optional_bool_value


_LANGUAGES = {
    "zh", "en", "de", "fr", "es", "id", "ja", "pt", "ko", "tr", "ms",
    "nl", "ro", "pl", "cs", "ar", "th", "vi", "ru", "it", "yue-CN", "sh-CN", "zhen",
}
_CLONE_LANGUAGES = {"zh", "en", "de", "fr", "es", "id", "ja", "pt", "zhen"}
_PUBLIC_SPEAKERS = {
    "zh_female_vv_uranus_bigtts",
    "zh_male_jingqiangkanye_emo_mars_bigtts",
}
_SOURCE_EVENTS = {ast.SOURCE_SUBTITLE_RESPONSE, ast.SOURCE_SUBTITLE_END}
_TRANSLATION_EVENTS = {ast.TRANSLATION_SUBTITLE_RESPONSE, ast.TRANSLATION_SUBTITLE_END}


class DoubaoSimultaneousInterpretation(HostBoundService):
    @staticmethod
    def _message_audio(messages: object) -> str:
        if not isinstance(messages, list):
            return ""
        for message in reversed(messages):
            if not isinstance(message, dict) or message.get("role") != "user":
                continue
            content = message.get("content")
            for item in content if isinstance(content, list) else []:
                if isinstance(item, dict) and item.get("type") == "reference_resource" and item.get("kind") == "audio":
                    return str(item.get("uri") or "").strip()
        return ""

    @staticmethod
    def _local_pcm_wav(value: object) -> bytes:
        uri = str(value or "").strip()
        path = uri[7:] if uri.startswith("file://") else uri
        if uri.startswith(("http://", "https://", "asset://")) or not os.path.isfile(path):
            raise ValueError("simultrans requires a local WAV attachment or path.")
        if os.path.splitext(path)[1].lower() != ".wav":
            raise ValueError("simultrans requires WAV input.")
        with wave.open(path, "rb") as source:
            if source.getframerate() != 16000 or source.getsampwidth() != 2 or source.getnchannels() != 1:
                raise ValueError("simultrans WAV input must be 16 kHz, 16-bit, mono PCM.")
            frames = source.readframes(source.getnframes())
        if not frames:
            raise ValueError("simultrans WAV input is empty.")
        return frames

    @staticmethod
    def _json_value(name: str, value: object, expected: type, default):
        if value in (None, ""):
            return default
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, expected):
            raise ValueError(f"{name} must be a JSON {expected.__name__}.")
        return parsed

    @staticmethod
    def _ws_url(base: object) -> str:
        value = str(base or "https://openspeech.bytedance.com").rstrip("/")
        if value.startswith("https://"):
            value = "wss://" + value[8:]
        elif value.startswith("http://"):
            value = "ws://" + value[7:]
        if not value.startswith(("ws://", "wss://")):
            raise ValueError("speechBaseUrl must use http(s) or ws(s).")
        return value + "/api/v4/ast/v2/translate"

    @staticmethod
    def _emit(host: object, event: dict) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if callable(callback):
            callback(event)

    def run_simultaneous_interpretation(
        self,
        messages: object,
        *,
        simultrans_source_audio: object = "",
        simultrans_mode: object = "s2t",
        simultrans_source_language: object = "zh",
        simultrans_target_language: object = "en",
        simultrans_speaker: object = "",
        simultrans_target_format: object = "ogg_opus",
        simultrans_target_rate: object = 24000,
        simultrans_hot_words: object = "",
        simultrans_glossary: object = "",
        simultrans_boosting_table_id: object = "",
        simultrans_boosting_table_name: object = "",
        simultrans_correct_table_id: object = "",
        simultrans_correct_table_name: object = "",
        simultrans_denoise: object = False,
        simultrans_enable_speaker_info: object = False,
        simultrans_resource_id: object = "volc.service_type.10053",
        simultrans_chunk_ms: object = 80,
        audio_filename_prefix: object = "simultaneous_interpretation",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        api_key = resolve_doubao_x_api_key(self.config)
        app_id = str(self.config.get("speechAppId") or "").strip()
        access_key = str(self.config.get("speechAccessKey") or "").strip()
        if not api_key and not (app_id and access_key):
            raise ValueError("simultrans requires provider xApiKey, or legacy speechAppId and speechAccessKey.")
        mode = str(simultrans_mode or "s2t").strip().lower()
        if mode not in {"s2t", "s2s"}:
            raise ValueError("simultrans_mode must be s2t or s2s.")
        source_language = str(simultrans_source_language or "").strip()
        target_language = str(simultrans_target_language or "").strip()
        if source_language not in _LANGUAGES or target_language not in _LANGUAGES:
            raise ValueError("simultrans source and target languages must use documented language codes.")
        if "zhen" in {source_language, target_language} and {source_language, target_language} != {"zhen"}:
            raise ValueError("simultrans zhen mode requires both source and target language to be zhen.")
        speaker = str(simultrans_speaker or "").strip()
        if source_language != "zhen" and "zh" not in {source_language, target_language} and "en" not in {source_language, target_language}:
            raise ValueError("simultrans requires source or target language to be zh or en.")
        if mode == "s2s" and speaker in _PUBLIC_SPEAKERS and target_language not in {"zh", "en", "zhen"}:
            raise ValueError("simultrans public-speaker s2s output only supports zh, en, or zhen.")
        if mode == "s2s" and speaker not in _PUBLIC_SPEAKERS:
            if source_language not in _CLONE_LANGUAGES or target_language not in _CLONE_LANGUAGES:
                raise ValueError("simultrans cloned-speaker s2s mode only supports the documented eight-language set.")
        chunk_ms = int(simultrans_chunk_ms)
        if chunk_ms != 80:
            raise ValueError("simultrans_chunk_ms must be 80 as recommended by the official protocol.")
        pcm = self._local_pcm_wav(self._message_audio(messages) or simultrans_source_audio)

        target_format = str(simultrans_target_format or "ogg_opus").strip().lower()
        target_rate = int(simultrans_target_rate)
        if mode == "s2s":
            if target_format not in {"pcm", "ogg_opus"}:
                raise ValueError("simultrans_target_format must be pcm or ogg_opus.")
            if target_rate not in {16000, 24000}:
                raise ValueError("simultrans_target_rate must be 16000 or 24000.")
        hot_words = self._json_value("simultrans_hot_words", simultrans_hot_words, list, [])
        if any(not isinstance(item, str) or not item.strip() for item in hot_words):
            raise ValueError("simultrans_hot_words must be a JSON string array.")
        glossary = self._json_value("simultrans_glossary", simultrans_glossary, dict, {})
        if any(not isinstance(key, str) or not isinstance(value, str) for key, value in glossary.items()):
            raise ValueError("simultrans_glossary must map strings to strings.")

        session_id = str(uuid.uuid4())
        resource_id = str(simultrans_resource_id or "").strip()
        if not resource_id:
            raise ValueError("simultrans_resource_id is required.")
        start = ast.TranslateRequest(event=ast.START_SESSION)
        start.request_meta.session_id = session_id
        start.user.uid = app_id or api_key
        start.user.platform = "AgentPark"
        start.source_audio.format = "wav"
        start.source_audio.codec = "raw"
        start.source_audio.rate = 16000
        start.source_audio.bits = 16
        start.source_audio.channel = 1
        if mode == "s2s":
            start.target_audio.format = target_format
            start.target_audio.rate = target_rate
        start.request.mode = mode
        start.request.source_language = source_language
        start.request.target_language = target_language
        if speaker:
            start.request.speaker_id = speaker
        start.request.corpus.hot_words_list.extend([item.strip() for item in hot_words])
        start.request.corpus.glossary_list.update(glossary)
        start.request.corpus.boosting_table_id = str(simultrans_boosting_table_id or "").strip()
        start.request.corpus.boosting_table_name = str(simultrans_boosting_table_name or "").strip()
        start.request.corpus.correct_table_id = str(simultrans_correct_table_id or "").strip()
        start.request.corpus.correct_table_name = str(simultrans_correct_table_name or "").strip()
        start.denoise = bool(parse_optional_bool_value("simultrans_denoise", simultrans_denoise))
        start.enable_speaker_info = bool(parse_optional_bool_value(
            "simultrans_enable_speaker_info", simultrans_enable_speaker_info,
        ))

        headers = {"X-Api-Resource-Id": resource_id}
        if api_key:
            headers["X-Api-Key"] = api_key
        else:
            headers["X-Api-App-Id"] = app_id
            headers["X-Api-Access-Key"] = access_key
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        from websockets.sync.client import connect

        audio = bytearray()
        source_segments: list[str] = []
        translation_segments: list[str] = []
        source_current = ""
        translation_current = ""
        metadata: list[dict] = []
        sequence = 0
        if mode == "s2s":
            ext, mime = ("ogg", "audio/ogg") if target_format == "ogg_opus" else ("pcm", "audio/L16")
            stream_rate = 48000 if target_format == "ogg_opus" else target_rate
            self._emit(self.host, build_audio_stream_start(
                stream_id=session_id, mime=mime, audio_format=target_format, sample_rate=stream_rate,
            ))
        with acquire_provider_pressure(self.host):
            connection = connect(
                self._ws_url(self.config.get("speechBaseUrl")),
                additional_headers=headers,
                open_timeout=min(10, timeout),
                ping_interval=20,
                ping_timeout=20,
                close_timeout=5,
                max_size=None,
            )
            try:
                connection.send(start.SerializeToString())
                self._receive_started(connection, timeout)
                chunk_size = 16000 * 2 * chunk_ms // 1000
                chunks = [pcm[offset:offset + chunk_size] for offset in range(0, len(pcm), chunk_size)]
                for index, chunk in enumerate(chunks):
                    raise_if_cancel_requested(self._cancel_source())
                    request = ast.TranslateRequest(event=ast.TASK_REQUEST)
                    request.source_audio.binary_data = chunk
                    connection.send(request.SerializeToString())
                    if index < len(chunks) - 1:
                        sleep_with_cancel(chunk_ms / 1000, self._cancel_source())
                connection.send(ast.TranslateRequest(event=ast.FINISH_SESSION).SerializeToString())

                while True:
                    raise_if_cancel_requested(self._cancel_source())
                    response = self._recv(connection, timeout)
                    self._raise_for_response(response)
                    if response.event in _SOURCE_EVENTS:
                        source_current = response.text.strip() or source_current
                        if response.event == ast.SOURCE_SUBTITLE_END and source_current:
                            source_segments.append(source_current)
                            source_current = ""
                    elif response.event in _TRANSLATION_EVENTS:
                        previous = self._joined(translation_segments, translation_current)
                        translation_current = response.text.strip() or translation_current
                        if response.event == ast.TRANSLATION_SUBTITLE_END and translation_current:
                            translation_segments.append(translation_current)
                            translation_current = ""
                        current = self._joined(translation_segments, translation_current)
                        self._emit_text(self.host, previous, current)
                    elif response.event == ast.TTS_RESPONSE and response.data:
                        audio.extend(response.data)
                        for offset in range(0, len(response.data), 2048):
                            self._emit(self.host, build_audio_stream_chunk(
                                stream_id=session_id,
                                sequence=sequence,
                                data=response.data[offset:offset + 2048],
                            ))
                            sequence += 1
                    if response.response_meta.status_code or response.response_meta.message:
                        metadata.append({
                            "event": response.event,
                            "status_code": response.response_meta.status_code,
                            "message": response.response_meta.message,
                        })
                    if response.event == ast.SESSION_FINISHED:
                        break
            finally:
                connection.close()

        source_text = self._joined(source_segments, source_current)
        translation_text = self._joined(translation_segments, translation_current)
        result = {
            "response": translation_text,
            "source_transcription": source_text,
            "translation": translation_text,
            "session_id": session_id,
            "events": metadata,
        }
        if mode == "s2s":
            if not audio:
                raise ValueError("Doubao simultrans s2s completed without audio data.")
            self._emit(self.host, build_audio_stream_end(stream_id=session_id, sequence=sequence))
            save_dir = os.path.dirname(self.current_memory_path)
            os.makedirs(save_dir, exist_ok=True)
            prefix = str(audio_filename_prefix or "simultaneous_interpretation").strip() or "simultaneous_interpretation"
            path = os.path.join(save_dir, f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.{ext}")
            with open(path, "wb") as handle:
                handle.write(audio)
            result["audio_path"] = path
            result["stream_id"] = session_id
        if not translation_text:
            raise ValueError("Doubao simultrans completed without translated text.")
        return result

    def _receive_started(self, connection, timeout: float) -> None:
        while True:
            response = self._recv(connection, timeout)
            self._raise_for_response(response)
            if response.event == ast.SESSION_STARTED:
                return

    @staticmethod
    def _recv(connection, timeout: float):
        raw = connection.recv(timeout=timeout)
        if not isinstance(raw, bytes):
            raise ValueError("Doubao simultrans returned a text frame.")
        response = ast.TranslateResponse()
        try:
            response.ParseFromString(raw)
        except Exception as exc:
            raise ValueError("Doubao simultrans returned invalid protobuf.") from exc
        return response

    @staticmethod
    def _raise_for_response(response) -> None:
        if response.event == ast.SESSION_FAILED:
            raise ValueError(
                f"Doubao simultrans session failed {response.response_meta.status_code}: "
                f"{response.response_meta.message}"
            )
        status = response.response_meta.status_code
        if status not in {0, 20000000}:
            raise ValueError(f"Doubao simultrans error {status}: {response.response_meta.message}")

    @staticmethod
    def _joined(completed: list[str], current: str) -> str:
        return "\n".join([*completed, *([current] if current else [])])

    @staticmethod
    def _emit_text(host: object, previous: str, current: str) -> None:
        callback = getattr(host, "tool_event_callback", None)
        if not callable(callback) or previous == current:
            return
        extends = current.startswith(previous)
        callback(build_node_message_delta(
            current[len(previous):] if extends else current,
            current,
            force=not extends,
        ))
