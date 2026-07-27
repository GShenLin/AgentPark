import json
import time
import urllib.parse

from src.providers.agnes_video_generation_contract import build_agnes_video_payload
from src.providers.doubao_video_generation import DoubaoVideoGeneration
from src.value_parsing import parse_optional_float_value


class AgnesVideoGeneration(DoubaoVideoGeneration):
    _TERMINAL_STATUSES = {"completed", "failed"}

    def _build_create_url(self) -> str:
        base_url = self.config["baseUrl"].rstrip("/")
        return base_url if base_url.endswith("/videos") else f"{base_url}/videos"

    def _build_result_url(self, video_id: str) -> str:
        base_url = self.config["baseUrl"].rstrip("/")
        gateway_root = base_url[:-3] if base_url.endswith("/v1") else base_url
        query = urllib.parse.urlencode({"video_id": video_id})
        return f"{gateway_root}/agnesapi?{query}"

    def _poll_video_result(self, video_id, *, poll_interval_sec, max_wait_sec):
        headers = {"Authorization": f"Bearer {self.config['apiKey']}"}
        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        started = time.monotonic()
        while True:
            result = self._get_json_with_retry(
                endpoint="agnesapi",
                url=self._build_result_url(video_id),
                headers=headers,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            if str(result.get("status") or "").strip().lower() in self._TERMINAL_STATUSES:
                return result
            if max_wait_sec is not None and time.monotonic() - started >= max_wait_sec:
                raise TimeoutError(
                    f"Agnes video generation timed out after {max_wait_sec:.0f}s. video_id={video_id}"
                )
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
        **_unused_options,
    ):
        read_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_config):
            self.config = read_config()
        use_model = self._resolve_video_model(model=model)
        payload = build_agnes_video_payload(
            model=use_model,
            content=content,
            resolution=resolution,
            ratio=ratio,
            duration=duration,
            frames=frames,
            seed=seed,
            frame_rate=self.config.get("videoFrameRate", 24),
            negative_prompt=self.config.get("videoNegativePrompt"),
        )
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        create_result = self._post_json_with_retry(
            endpoint="videos",
            url=self._build_create_url(),
            headers=headers,
            payload_json=json.dumps(payload, ensure_ascii=False),
            max_retries=int(self.config.get("maxRetries", 2)),
            retry_delay=float(self.config.get("retryDelaySec", 1)),
        )
        video_id = str(create_result.get("video_id") or "").strip()
        task_id = str(create_result.get("task_id") or create_result.get("id") or "").strip()
        if not video_id:
            raise ValueError(
                f"Agnes video creation returned no video_id: {json.dumps(create_result, ensure_ascii=False)}"
            )

        poll_interval = parse_optional_float_value(
            "videoPollIntervalSec",
            self.config.get("videoPollIntervalSec", 10),
            minimum_exclusive=0,
        ) or 10.0
        max_wait = parse_optional_float_value(
            "videoMaxWaitSec",
            self.config.get("videoMaxWaitSec", 900),
            minimum_exclusive=0,
        )
        result = self._poll_video_result(
            video_id, poll_interval_sec=poll_interval, max_wait_sec=max_wait
        )
        status = str(result.get("status") or "").strip().lower()
        if status != "completed":
            raise RuntimeError(
                f"Agnes video generation failed: {json.dumps(result.get('error'), ensure_ascii=False)}"
            )
        metadata = result.get("metadata")
        video_url = str(metadata.get("url") or "").strip() if isinstance(metadata, dict) else ""
        if not video_url:
            raise ValueError(
                f"Agnes video result returned no metadata.url: {json.dumps(result, ensure_ascii=False)}"
            )
        video_path = self._save_video_file(video_url, filename_prefix)
        self.Message("assistant", json.dumps({
            "task_id": task_id,
            "video_id": video_id,
            "model": use_model,
            "status": status,
            "video_url": video_url,
            "saved_files": [video_path],
        }, ensure_ascii=False))
        return {
            "response": f"Video generated successfully: {video_path}",
            "video_path": video_path,
            "task_id": task_id,
            "video_id": video_id,
            "video_url": video_url,
            "status": "success",
        }
