"""Doubao section 7 audio-minutes submit/query runtime."""
from __future__ import annotations

import json
import time
import uuid

from src.runtime_cancellation import sleep_with_cancel
from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value


class DoubaoAudioMinutes(HostBoundService):
    @staticmethod
    def _positive_number(name: str, value: object, default: float) -> float:
        try:
            result = float(default if value in (None, "") else value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{name} must be a positive number.") from exc
        if result <= 0:
            raise ValueError(f"{name} must be a positive number.")
        return result

    @staticmethod
    def _json_strings(name: str, value: object) -> list[str]:
        if value in (None, ""):
            return []
        parsed = value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError as exc:
                raise ValueError(f"{name} must be valid JSON: {exc}") from exc
        if not isinstance(parsed, list) or any(not isinstance(item, str) or not item.strip() for item in parsed):
            raise ValueError(f"{name} must be a JSON string array.")
        return [item.strip() for item in parsed]

    def _headers(self, *, resource_id: str, request_id: str, sequence: bool) -> dict[str, str]:
        app_id = str(self.config.get("speechAppId") or "").strip()
        access_key = str(self.config.get("speechAccessKey") or "").strip()
        if not app_id or not access_key:
            raise ValueError("minutes requires provider speechAppId and speechAccessKey as documented for the legacy endpoint.")
        headers = {
            "Content-Type": "application/json",
            "X-Api-App-Key": app_id,
            "X-Api-Access-Key": access_key,
            "X-Api-Resource-Id": resource_id,
            "X-Api-Request-Id": request_id,
        }
        if sequence:
            headers["X-Api-Sequence"] = "-1"
        return headers

    def generate_minutes(
        self,
        messages: object,
        *,
        minutes_source_url: object = "",
        minutes_file_type: object = "audio",
        minutes_source_language: object = "zh_cn",
        minutes_all_activate: object = True,
        minutes_speaker_identification: object = True,
        minutes_number_of_speakers: object = 0,
        minutes_hot_words: object = "",
        minutes_need_word_time_series: object = True,
        minutes_translation_enabled: object = False,
        minutes_target_language: object = "en_us",
        minutes_information_types: object = "",
        minutes_summarization_enabled: object = True,
        minutes_chapter_enabled: object = True,
        minutes_resource_id: object = "volc.lark.minutes",
        minutes_poll_interval_seconds: object = 30,
        minutes_poll_timeout_seconds: object = 7200,
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        source_url = str(minutes_source_url or "").strip()
        if not source_url.startswith(("http://", "https://")):
            raise ValueError("minutes_source_url must be a public HTTP(S) audio or video URL.")
        file_type = str(minutes_file_type or "audio").strip().lower()
        if file_type not in {"audio", "video"}:
            raise ValueError("minutes_file_type must be audio or video.")
        source_language = str(minutes_source_language or "zh_cn").strip()
        if source_language not in {"zh_cn", "en_us"}:
            raise ValueError("minutes_source_language must be zh_cn or en_us.")
        all_activate = bool(parse_optional_bool_value("minutes_all_activate", minutes_all_activate))
        translation = bool(parse_optional_bool_value("minutes_translation_enabled", minutes_translation_enabled))
        summarization = bool(parse_optional_bool_value("minutes_summarization_enabled", minutes_summarization_enabled))
        chapter = bool(parse_optional_bool_value("minutes_chapter_enabled", minutes_chapter_enabled))
        information_types = self._json_strings("minutes_information_types", minutes_information_types)
        if not all_activate and not (translation or summarization or chapter or information_types):
            raise ValueError("minutes requires at least one additional analysis feature when minutes_all_activate is false.")
        params: dict = {
            "AllActivate": all_activate,
            "SourceLang": source_language,
            "AudioTranscriptionEnable": True,
            "AudioTranscriptionParams": {
                "SpeakerIdentification": bool(parse_optional_bool_value(
                    "minutes_speaker_identification", minutes_speaker_identification,
                )),
                "NumberOfSpeaker": int(minutes_number_of_speakers),
                "HotWords": str(minutes_hot_words or "").strip(),
                "NeedWordTimeSeries": bool(parse_optional_bool_value(
                    "minutes_need_word_time_series", minutes_need_word_time_series,
                )),
            },
            "TranslationEnable": translation,
            "InformationExtractionEnabled": bool(information_types),
            "SummarizationEnabled": summarization,
            "ChapterEnabled": chapter,
        }
        if translation:
            target = str(minutes_target_language or "").strip()
            if target not in {"zh_cn", "en_us"}:
                raise ValueError("minutes_target_language must be zh_cn or en_us.")
            params["TranslationParams"] = {"TargetLang": target}
        if information_types:
            allowed = {"todo_list", "question_answer"}
            if any(item not in allowed for item in information_types):
                raise ValueError("minutes_information_types only supports todo_list and question_answer.")
            params["InformationExtractionParams"] = {"Types": information_types}
        if summarization:
            params["SummarizationParams"] = {"Types": ["summary"]}

        resource_id = str(minutes_resource_id or "volc.lark.minutes").strip()
        if not resource_id:
            raise ValueError("minutes_resource_id is required.")
        request_id = str(uuid.uuid4())
        base = str(self.config.get("speechBaseUrl") or "https://openspeech.bytedance.com").rstrip("/")
        timeout = float(self.config.get("timeoutMs", 60000)) / 1000
        submit = self._curl_post_once_raw(
            url=base + "/api/v3/auc/lark/submit",
            headers=self._headers(resource_id=resource_id, request_id=request_id, sequence=True),
            payload_json=json.dumps({
                "Input": {"Offline": {"FileURL": source_url, "FileType": file_type}},
                "Params": params,
            }, ensure_ascii=False),
            timeout_sec=min(timeout, 5),
            marker="__DOUBAO_MINUTES_SUBMIT_CODE__:",
        )
        body = self._body(submit.body, "submit")
        status_code = str(submit.headers.get("x-api-status-code") or "").strip()
        data = body.get("Data") if isinstance(body.get("Data"), dict) else {}
        task_id = str(data.get("TaskID") or "").strip()
        if submit.status_code != 200 or status_code != "20000000" or not task_id:
            raise ValueError(f"Doubao minutes submit failed: HTTP {submit.status_code}, status {status_code or '<missing>'}")

        poll_interval = self._positive_number("minutes_poll_interval_seconds", minutes_poll_interval_seconds, 30)
        poll_timeout = self._positive_number("minutes_poll_timeout_seconds", minutes_poll_timeout_seconds, 7200)
        started = time.monotonic()
        while True:
            query = self._curl_post_once_raw(
                url=base + "/api/v3/auc/lark/query",
                headers=self._headers(resource_id=resource_id, request_id=task_id, sequence=False),
                payload_json=json.dumps({"TaskID": task_id}),
                timeout_sec=min(timeout, 5),
                marker="__DOUBAO_MINUTES_QUERY_CODE__:",
            )
            result_body = self._body(query.body, "query")
            query_status = str(query.headers.get("x-api-status-code") or "").strip()
            result_data = result_body.get("Data") if isinstance(result_body.get("Data"), dict) else {}
            task_status = str(result_data.get("Status") or "").strip().lower()
            if query.status_code != 200 or query_status != "20000000":
                raise ValueError(f"Doubao minutes query failed: HTTP {query.status_code}, status {query_status or '<missing>'}")
            if task_status == "success":
                result = result_data.get("Result") if isinstance(result_data.get("Result"), dict) else {}
                return {
                    "response": "Audio minutes completed successfully.",
                    "minutes": result,
                    "task_id": task_id,
                }
            if task_status == "failed":
                raise ValueError(
                    f"Doubao minutes task failed {result_data.get('ErrCode')}: {result_data.get('ErrMessage') or ''}"
                )
            if task_status != "running":
                raise ValueError(f"Doubao minutes returned unknown task status: {task_status or '<missing>'}")
            if time.monotonic() - started >= poll_timeout:
                raise TimeoutError(f"Doubao minutes timed out after {poll_timeout:g}s. task_id={task_id}")
            sleep_with_cancel(poll_interval, self._cancel_source())

    @staticmethod
    def _body(value: str, stage: str) -> dict:
        try:
            body = json.loads(value)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Doubao minutes {stage} returned invalid JSON.") from exc
        if not isinstance(body, dict):
            raise ValueError(f"Doubao minutes {stage} response must be a JSON object.")
        return body
