import json
import os
import time
import urllib.parse
from datetime import datetime

from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value, parse_optional_float_value, parse_optional_int_value


class DoubaoVideoGeneration(HostBoundService):
    _TASKS_ENDPOINT = "/contents/generations/tasks"
    _TERMINAL_STATUSES = {"succeeded", "failed", "cancelled"}

    @staticmethod
    def _guess_ext_from_url(raw_url):
        try:
            parsed = urllib.parse.urlparse(str(raw_url or "").strip())
            path = parsed.path or ""
            filename = os.path.basename(path)
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].strip().lower()
                if 1 <= len(ext) <= 5:
                    return ext
        except Exception:
            pass
        return "mp4"

    def _build_tasks_url(self, task_id=None):
        base_url = self.config["baseUrl"].rstrip("/")
        if base_url.endswith(self._TASKS_ENDPOINT):
            tasks_url = base_url
        else:
            tasks_url = f"{base_url}{self._TASKS_ENDPOINT}"
        if task_id:
            return f"{tasks_url}/{task_id}"
        return tasks_url

    def _resolve_video_model(self, model=None):
        use_model = (
            model
            or self.config.get("videoModel")
            or self.config.get("video_model")
            or self.config.get("videoModelId")
            or self.config.get("model")
        )
        if not use_model:
            raise ValueError("DouBao video model is required for video generation.")
        return use_model

    def _normalize_content(self, content):
        if not isinstance(content, list) or not content:
            raise ValueError("Video generation content must be a non-empty list.")

        normalized = []
        for item in content:
            if not isinstance(item, dict):
                raise ValueError("Video generation content items must be objects.")
            item_type = str(item.get("type") or "").strip()
            if item_type not in {"text", "image_url", "video_url", "audio_url"}:
                raise ValueError(f"Unsupported video generation content type: {item_type or '<empty>'}")
            normalized.append(dict(item))
        return normalized

    def _resolve_create_payload(
        self,
        *,
        model,
        content,
        resolution=None,
        ratio=None,
        duration=None,
        frames=None,
        seed=None,
        camera_fixed=None,
        watermark=None,
        generate_audio=None,
        callback_url=None,
        return_last_frame=None,
        service_tier=None,
        execution_expires_after=None,
        safety_identifier=None,
        tools=None,
    ):
        payload = {
            "model": model,
            "content": self._normalize_content(content),
        }

        resolved_resolution = str(
            resolution
            or self.config.get("videoResolution")
            or self.config.get("resolution")
            or ""
        ).strip()
        if resolved_resolution:
            payload["resolution"] = resolved_resolution

        resolved_ratio = str(ratio or self.config.get("videoRatio") or self.config.get("ratio") or "").strip()
        if resolved_ratio:
            payload["ratio"] = resolved_ratio

        resolved_duration = parse_optional_int_value(
            "duration",
            duration if duration is not None else self.config.get("videoDuration", self.config.get("duration")),
            allowed_values=(-1,),
            minimum=1,
        )
        if resolved_duration is not None:
            payload["duration"] = resolved_duration

        resolved_frames = parse_optional_int_value(
            "frames",
            frames if frames is not None else self.config.get("videoFrames", self.config.get("frames")),
            minimum=1,
        )
        if resolved_frames is not None:
            payload["frames"] = resolved_frames

        resolved_seed = parse_optional_int_value(
            "seed",
            seed if seed is not None else self.config.get("videoSeed", self.config.get("seed")),
            allowed_values=(-1,),
            minimum=0,
            maximum=4294967295,
        )
        if resolved_seed is not None:
            payload["seed"] = resolved_seed

        resolved_camera_fixed = parse_optional_bool_value(
            "camera_fixed",
            camera_fixed if camera_fixed is not None else self.config.get("videoCameraFixed", self.config.get("cameraFixed")),
        )
        if resolved_camera_fixed is not None:
            payload["camera_fixed"] = resolved_camera_fixed

        resolved_watermark = parse_optional_bool_value(
            "watermark",
            watermark if watermark is not None else self.config.get("videoWatermark", self.config.get("watermark"))
        )
        if resolved_watermark is not None:
            payload["watermark"] = resolved_watermark

        resolved_generate_audio = parse_optional_bool_value(
            "generate_audio",
            generate_audio
            if generate_audio is not None
            else self.config.get("videoGenerateAudio", self.config.get("generateAudio"))
        )
        if resolved_generate_audio is not None:
            payload["generate_audio"] = resolved_generate_audio

        resolved_callback_url = str(
            callback_url
            or self.config.get("videoCallbackUrl")
            or self.config.get("callbackUrl")
            or ""
        ).strip()
        if resolved_callback_url:
            payload["callback_url"] = resolved_callback_url

        resolved_return_last_frame = parse_optional_bool_value(
            "return_last_frame",
            return_last_frame
            if return_last_frame is not None
            else self.config.get("videoReturnLastFrame", self.config.get("returnLastFrame")),
        )
        if resolved_return_last_frame is not None:
            payload["return_last_frame"] = resolved_return_last_frame

        resolved_service_tier = str(
            service_tier
            or self.config.get("videoServiceTier")
            or self.config.get("serviceTier")
            or ""
        ).strip()
        if resolved_service_tier:
            payload["service_tier"] = resolved_service_tier

        resolved_execution_expires_after = parse_optional_int_value(
            "execution_expires_after",
            execution_expires_after
            if execution_expires_after is not None
            else self.config.get("videoExecutionExpiresAfter", self.config.get("executionExpiresAfter")),
            minimum=3600,
            maximum=259200,
        )
        if resolved_execution_expires_after is not None:
            payload["execution_expires_after"] = resolved_execution_expires_after

        resolved_safety_identifier = str(
            safety_identifier
            or self.config.get("videoSafetyIdentifier")
            or self.config.get("safetyIdentifier")
            or ""
        ).strip()
        if resolved_safety_identifier:
            payload["safety_identifier"] = resolved_safety_identifier

        if isinstance(tools, list) and tools:
            payload["tools"] = tools

        return payload

    def _extract_video_url(self, task_result):
        content = task_result.get("content")
        if isinstance(content, dict):
            direct = content.get("video_url")
            if isinstance(direct, str) and direct.strip():
                return direct.strip()
            if isinstance(direct, dict):
                nested = str(direct.get("url") or "").strip()
                if nested:
                    return nested
        return ""

    def _extract_last_frame_url(self, task_result):
        content = task_result.get("content")
        if isinstance(content, dict):
            direct = content.get("last_frame_url")
            if isinstance(direct, str) and direct.strip():
                return direct.strip()
            if isinstance(direct, dict):
                nested = str(direct.get("url") or "").strip()
                if nested:
                    return nested
        return ""

    def _save_video_file(self, video_url, filename_prefix):
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)

        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        if not filename_prefix.startswith(f"{agent_id}_"):
            filename_prefix = f"{agent_id}_{filename_prefix}"

        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        video_bytes = self._curl_get_bytes_with_retry(
            url=video_url,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        ext = self._guess_ext_from_url(video_url)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(save_dir, f"{filename_prefix}_{ts}.{ext}")
        with open(file_path, "wb") as f:
            f.write(video_bytes)
        return file_path

    def _poll_task_result(self, task_id, *, poll_interval_sec, max_wait_sec):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        task_url = self._build_tasks_url(task_id=task_id)
        started = time.monotonic()

        while True:
            task_result = self._get_json_with_retry(
                endpoint=f"contents/generations/tasks/{task_id}",
                url=task_url,
                headers=headers,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            status = str(task_result.get("status") or "").strip().lower()
            if status in self._TERMINAL_STATUSES:
                return task_result

            if max_wait_sec is not None and (time.monotonic() - started) >= max_wait_sec:
                raise TimeoutError(f"Video generation task timed out after {max_wait_sec:.0f}s. task_id={task_id}")

            time.sleep(poll_interval_sec)

    def generate_video(
        self,
        content,
        *,
        model=None,
        filename_prefix="generated_video",
        resolution=None,
        ratio=None,
        duration=None,
        frames=None,
        seed=None,
        camera_fixed=None,
        watermark=None,
        generate_audio=None,
        callback_url=None,
        return_last_frame=None,
        service_tier=None,
        execution_expires_after=None,
        safety_identifier=None,
        tools=None,
    ):
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        use_model = self._resolve_video_model(model=model)
        payload = self._resolve_create_payload(
            model=use_model,
            content=content,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            frames=frames,
            seed=seed,
            camera_fixed=camera_fixed,
            watermark=watermark,
            generate_audio=generate_audio,
            callback_url=callback_url,
            return_last_frame=return_last_frame,
            service_tier=service_tier,
            execution_expires_after=execution_expires_after,
            safety_identifier=safety_identifier,
            tools=tools,
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        payload_json = json.dumps(payload, ensure_ascii=False)
        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))

        create_result = self._post_json_with_retry(
            endpoint="contents/generations/tasks",
            url=self._build_tasks_url(),
            headers=headers,
            payload_json=payload_json,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        task_id = str(create_result.get("id") or "").strip()
        if not task_id:
            raise ValueError(f"Unexpected task creation response: {json.dumps(create_result, ensure_ascii=False)}")

        poll_interval_sec = parse_optional_float_value(
            "videoPollIntervalSec",
            self.config.get("videoPollIntervalSec", self.config.get("contentGenerationPollIntervalSec", 10)),
            minimum_exclusive=0,
        )
        if poll_interval_sec is None:
            poll_interval_sec = 10.0

        max_wait_sec = parse_optional_float_value(
            "videoMaxWaitSec",
            self.config.get("videoMaxWaitSec", self.config.get("contentGenerationMaxWaitSec", 900)),
            minimum_exclusive=0,
        )

        task_result = self._poll_task_result(
            task_id,
            poll_interval_sec=poll_interval_sec,
            max_wait_sec=max_wait_sec,
        )
        status = str(task_result.get("status") or "").strip().lower()
        if status != "succeeded":
            error = task_result.get("error")
            raise RuntimeError(
                f"Video generation task failed: status={status or '<empty>'}, error={json.dumps(error, ensure_ascii=False)}"
            )

        video_url = self._extract_video_url(task_result)
        last_frame_url = self._extract_last_frame_url(task_result)
        if not video_url:
            raise ValueError(f"Video generation task returned no video URL: {json.dumps(task_result, ensure_ascii=False)}")

        video_path = self._save_video_file(video_url, filename_prefix=filename_prefix)
        meta = {
            "task_id": task_id,
            "model": use_model,
            "status": status,
            "video_url": video_url,
            "saved_files": [video_path],
        }
        if last_frame_url:
            meta["last_frame_url"] = last_frame_url
        self.Message("assistant", json.dumps(meta, ensure_ascii=False))

        result = {
            "response": f"Video generated successfully: {video_path}",
            "video_path": video_path,
            "task_id": task_id,
            "video_url": video_url,
            "status": "success",
        }
        if last_frame_url:
            result["last_frame_url"] = last_frame_url
        return result
