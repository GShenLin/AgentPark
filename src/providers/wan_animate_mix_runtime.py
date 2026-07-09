import json
import os
import time
from datetime import datetime
from urllib.parse import urlparse

from src.service_host import HostBoundService
from src.value_parsing import parse_optional_bool_value, parse_optional_float_value


class WanAnimateMixRuntime(HostBoundService):
    _TASK_TERMINAL_STATUSES = {"SUCCEEDED", "FAILED", "CANCELED", "UNKNOWN"}

    def _build_create_url(self) -> str:
        base_url = str(self.config.get("baseUrl") or "").strip().rstrip("/")
        if not base_url:
            raise ValueError("Wan Animate Mix provider requires baseUrl.")
        return base_url

    def _build_task_url(self, task_id: str) -> str:
        override = str(self.config.get("taskStatusBaseUrl") or "").strip().rstrip("/")
        if override:
            return f"{override}/{task_id}"

        create_url = self._build_create_url()
        parsed = urlparse(create_url)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError(f"Invalid Wan Animate Mix baseUrl: {create_url}")
        return f"{parsed.scheme}://{parsed.netloc}/api/v1/tasks/{task_id}"

    def _resolve_mode(self, value):
        mode = str(value or self.config.get("wanAnimateMixMode") or "wan-std").strip()
        if mode not in {"wan-std", "wan-pro"}:
            raise ValueError("mode must be either 'wan-std' or 'wan-pro'.")
        return mode

    def _save_video_file(self, video_url: str, filename_prefix: str) -> str:
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

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        file_path = os.path.join(save_dir, f"{filename_prefix}_{ts}.mp4")
        with open(file_path, "wb") as file_obj:
            file_obj.write(video_bytes)
        return file_path

    def _poll_task_result(self, task_id: str, *, poll_interval_sec: float, max_wait_sec: float | None) -> dict:
        headers = {
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        url = self._build_task_url(task_id)
        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        started = time.monotonic()

        while True:
            result = self._get_json_with_retry(
                endpoint=f"tasks/{task_id}",
                url=url,
                headers=headers,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            output = result.get("output") if isinstance(result, dict) else {}
            task_status = str((output or {}).get("task_status") or "").strip().upper()
            if task_status in self._TASK_TERMINAL_STATUSES:
                return result

            if max_wait_sec is not None and (time.monotonic() - started) >= max_wait_sec:
                raise TimeoutError(f"Wan Animate Mix task timed out after {max_wait_sec:.0f}s. task_id={task_id}")

            time.sleep(poll_interval_sec)

    def generate_video_change_person(
        self,
        *,
        image_url: str,
        video_url: str,
        mode=None,
        watermark=None,
        check_image=None,
        filename_prefix="generated_video_change_person",
    ) -> dict:
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()

        model = str(self.config.get("model") or "").strip()
        if not model:
            raise ValueError("Wan Animate Mix provider requires model.")

        payload = {
            "model": model,
            "input": {
                "image_url": str(image_url or "").strip(),
                "video_url": str(video_url or "").strip(),
            },
            "parameters": {
                "mode": self._resolve_mode(mode),
            },
        }
        if not payload["input"]["image_url"]:
            raise ValueError("image_url is required")
        if not payload["input"]["video_url"]:
            raise ValueError("video_url is required")

        resolved_watermark = parse_optional_bool_value(
            "watermark",
            watermark if watermark is not None else self.config.get("watermark"),
        )
        if resolved_watermark is not None:
            payload["input"]["watermark"] = resolved_watermark

        resolved_check_image = parse_optional_bool_value(
            "check_image",
            check_image
            if check_image is not None
            else self.config.get("wanAnimateMixCheckImage"),
        )
        if resolved_check_image is not None:
            payload["parameters"]["check_image"] = resolved_check_image

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
            "X-DashScope-Async": "enable",
        }
        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        create_result = self._post_json_with_retry(
            endpoint="services/aigc/image2video/video-synthesis",
            url=self._build_create_url(),
            headers=headers,
            payload_json=json.dumps(payload, ensure_ascii=False),
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        output = create_result.get("output") if isinstance(create_result, dict) else {}
        task_id = str((output or {}).get("task_id") or "").strip()
        if not task_id:
            raise ValueError(f"Unexpected Wan Animate Mix task creation response: {json.dumps(create_result, ensure_ascii=False)}")

        poll_interval = parse_optional_float_value(
            "wanAnimateMixPollIntervalSec",
            self.config.get("wanAnimateMixPollIntervalSec", 15),
            minimum_exclusive=0,
        )
        if poll_interval is None:
            poll_interval = 15.0

        max_wait = parse_optional_float_value(
            "wanAnimateMixMaxWaitSec",
            self.config.get("wanAnimateMixMaxWaitSec", 900),
            minimum_exclusive=0,
        )
        if max_wait is None:
            max_wait = 900.0

        task_result = self._poll_task_result(
            task_id,
            poll_interval_sec=poll_interval,
            max_wait_sec=max_wait,
        )
        task_output = task_result.get("output") if isinstance(task_result, dict) else {}
        task_status = str((task_output or {}).get("task_status") or "").strip().upper()
        if task_status != "SUCCEEDED":
            raise RuntimeError(
                f"Wan Animate Mix task failed: status={task_status or '<empty>'}, "
                f"code={str((task_output or {}).get('code') or '').strip()}, "
                f"message={str((task_output or {}).get('message') or '').strip()}"
            )

        results = task_output.get("results") if isinstance(task_output, dict) else {}
        resolved_video_url = str((results or {}).get("video_url") or "").strip()
        if not resolved_video_url:
            raise ValueError(f"Wan Animate Mix task returned no video_url: {json.dumps(task_result, ensure_ascii=False)}")

        video_path = self._save_video_file(resolved_video_url, filename_prefix=filename_prefix)
        usage = task_result.get("usage") if isinstance(task_result, dict) else {}
        response = {
            "response": f"Video generated successfully: {video_path}",
            "video_path": video_path,
            "video_url": resolved_video_url,
            "task_id": task_id,
            "status": task_status.lower(),
            "request_id": str(task_result.get("request_id") or "").strip(),
        }
        if isinstance(usage, dict):
            if usage.get("video_duration") is not None:
                response["video_duration"] = usage.get("video_duration")
            if usage.get("video_ratio") is not None:
                response["video_ratio"] = usage.get("video_ratio")

        self.Message("assistant", json.dumps(response, ensure_ascii=False))
        return response
