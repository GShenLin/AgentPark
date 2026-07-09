import base64
import json
import os
import urllib.parse
from datetime import datetime

from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.service_host import HostBoundService


class DoubaoImageGeneration(ProviderRuntimeEventMixin, HostBoundService):
    def generate_image(
        self,
        prompt,
        model=None,
        filename_prefix="generated_image",
        size=None,
        response_format="url",
        watermark=False,
        image=None,
        sequential_image_generation=None,
        aspect_ratio=None,
        image_size=None,
    ):
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)

        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        if not filename_prefix.startswith(f"{agent_id}_"):
            filename_prefix = f"{agent_id}_{filename_prefix}"

        base_url = self.config["baseUrl"].rstrip("/")
        use_model = model or self.config.get("model")
        if not use_model:
            raise ValueError("DouBao image model is required for image generation.")
        use_size = size or image_size or self.config.get("imageSize") or "2K"

        endpoint_suffix = "/images/generations"
        if base_url.endswith(endpoint_suffix):
            url = base_url
        else:
            url = f"{base_url}{endpoint_suffix}"

        self._emit_provider_runtime_notice(
            message=f"Generating image with model {use_model}.",
            stage="image_generation_start",
        )

        payload = {
            "model": use_model,
            "prompt": str(prompt),
            "size": str(use_size),
            "response_format": response_format,
            "watermark": bool(watermark),
        }
        if image is not None:
            payload["image"] = image
        if sequential_image_generation is not None:
            payload["sequential_image_generation"] = sequential_image_generation
        if aspect_ratio:
            payload["aspect_ratio"] = str(aspect_ratio)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }

        payload_json = json.dumps(payload, ensure_ascii=False)
        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        result = self._post_json_with_retry(
            endpoint="images/generations",
            url=url,
            headers=headers,
            payload_json=payload_json,
            max_retries=max_retries,
            retry_delay=retry_delay,
        )

        data_items = result.get("data") or []
        if not data_items:
            raise ValueError(f"Unexpected response format: {json.dumps(result, ensure_ascii=False)}")

        saved_files = []

        def _guess_ext_from_url(raw_url):
            try:
                parsed = urllib.parse.urlparse(raw_url)
                path = parsed.path or ""
                filename = os.path.basename(path)
                if "." in filename:
                    ext = filename.rsplit(".", 1)[-1].strip().lower()
                    if 1 <= len(ext) <= 5:
                        return ext
            except Exception:
                pass
            return "png"

        def _write_bytes_to_file(content_bytes, ext):
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{filename_prefix}_{ts}_{len(saved_files) + 1}.{ext}"
            file_path = os.path.join(save_dir, filename)
            with open(file_path, "wb") as f:
                f.write(content_bytes)
            saved_files.append(file_path)

        for item in data_items:
            if not isinstance(item, dict):
                continue
            if response_format == "b64_json" or "b64_json" in item:
                data_b64 = item.get("b64_json")
                if not data_b64:
                    continue
                _write_bytes_to_file(base64.b64decode(data_b64), "png")
                continue

            image_url = item.get("url")
            if not image_url:
                continue

            ext = _guess_ext_from_url(image_url)
            img_bytes = self._curl_get_bytes_with_retry(
                url=image_url,
                max_retries=max_retries,
                retry_delay=retry_delay,
            )
            _write_bytes_to_file(img_bytes, ext)

        meta = {
            "model": use_model,
            "saved_files": saved_files,
        }
        self.Message("assistant", json.dumps(meta, ensure_ascii=False))

        if not saved_files:
            raise ValueError(f"No image data returned. Response: {json.dumps(result, ensure_ascii=False)}")

        return saved_files[0] if len(saved_files) == 1 else saved_files
