import base64
import json
import os
import urllib.parse
from datetime import datetime

from src.providers.curl_transport import CurlHttpTransport, CurlTransportError
from src.providers.openai_transport_errors import OpenAITransportError
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.runtime_cancellation import CancellationRequested, sleep_with_cancel
from src.service_host import HostBoundService


class OpenAIImageGeneration(CurlHttpTransport, ProviderRuntimeEventMixin, HostBoundService):
    @staticmethod
    def _decode_data_url(raw_url):
        text = str(raw_url or "")
        if not text.startswith("data:"):
            return None
        header, sep, payload = text.partition(",")
        if not sep:
            raise ValueError("Invalid image data URL: missing payload separator")
        if ";base64" not in header.lower():
            raise ValueError("Unsupported image data URL: only base64 data URLs are supported")
        mime = header[5:].split(";", 1)[0].strip().lower()
        ext_by_mime = {
            "image/png": "png",
            "image/jpeg": "jpg",
            "image/jpg": "jpg",
            "image/webp": "webp",
            "image/gif": "gif",
        }
        return base64.b64decode(payload), ext_by_mime.get(mime, "png")

    def _curl_get_bytes_with_retry(self, *, url, max_retries, retry_delay):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        for attempt in range(max_retries + 1):
            try:
                return self._curl_get_bytes_raw(url=url, timeout_sec=timeout)
            except CurlTransportError as exc:
                if attempt < max_retries:
                    self._emit_retry_notice(error=str(exc), delay=retry_delay, stage="openai_image_download_retry")
                    sleep_with_cancel(retry_delay, self._cancel_source())
                    continue
                raise OpenAITransportError(f"Image download failed after {max_retries} retries: {exc}") from exc
            except CancellationRequested:
                raise
        raise OpenAITransportError("Image download failed: max retries exceeded")

    @staticmethod
    def _guess_ext_from_url(raw_url):
        try:
            parsed = urllib.parse.urlparse(raw_url)
            filename = os.path.basename(parsed.path or "")
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].strip().lower()
                if 1 <= len(ext) <= 5:
                    return ext
        except Exception:
            pass
        return "png"

    @staticmethod
    def _image_generation_url(base_url):
        normalized = str(base_url or "").rstrip("/")
        endpoint_suffix = "/images/generations"
        if normalized.endswith(endpoint_suffix):
            return normalized
        return f"{normalized}{endpoint_suffix}"

    @staticmethod
    def _resolve_openai_size(size, image_size, aspect_ratio):
        raw_size = str(size or image_size or "").strip()
        if "x" in raw_size.lower():
            return raw_size

        normalized_size = raw_size.upper()
        normalized_ratio = str(aspect_ratio or "").strip()
        if normalized_size == "1K":
            one_k_sizes = {
                "1:1": "1024x1024",
                "3:4": "1024x1536",
                "4:3": "1536x1024",
            }
            mapped = one_k_sizes.get(normalized_ratio)
            if mapped:
                return mapped
        return raw_size

    def _write_bytes_to_file(self, *, save_dir, filename_prefix, saved_files, content_bytes, ext):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"{filename_prefix}_{ts}_{len(saved_files) + 1}.{ext}"
        file_path = os.path.join(save_dir, filename)
        with open(file_path, "wb") as handle:
            handle.write(content_bytes)
        saved_files.append(file_path)

    def generate_image(
        self,
        prompt,
        model=None,
        filename_prefix="generated_image",
        size=None,
        response_format="url",
        watermark=False,
        image=None,
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

        use_model = model or self.config.get("imageModel") or self.config.get("image_model") or self.config.get("model")
        if not use_model:
            raise ValueError("OpenAI image model is required for image generation.")

        payload = {
            "model": use_model,
            "prompt": str(prompt),
            "response_format": str(response_format or "url"),
        }
        use_size = self._resolve_openai_size(
            size or self.config.get("imageSize") or self.config.get("image_size"),
            image_size,
            aspect_ratio,
        )
        if use_size:
            payload["size"] = str(use_size)
        if image is not None:
            payload["image"] = image
        if aspect_ratio:
            payload["aspect_ratio"] = str(aspect_ratio)
        if watermark is not None:
            payload["watermark"] = bool(watermark)

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        payload_json = json.dumps(payload, ensure_ascii=False)

        self._emit_provider_runtime_notice(
            message=f"Generating image with model {use_model}.",
            stage="openai_image_generation_start",
        )

        result = self._post_json_with_retry(
            endpoint="images/generations",
            url=self._image_generation_url(self.config.get("baseUrl")),
            headers=headers,
            payload_json=payload_json,
        )

        data_items = result.get("data") if isinstance(result, dict) else None
        if not data_items:
            raise ValueError(f"Unexpected OpenAI image response format: {json.dumps(result, ensure_ascii=False)}")

        max_retries, retry_delay = self._resolve_retry_policy()
        saved_files = []
        for item in data_items:
            if not isinstance(item, dict):
                continue
            if payload["response_format"] == "b64_json" or "b64_json" in item:
                data_b64 = item.get("b64_json")
                if not data_b64:
                    continue
                self._write_bytes_to_file(
                    save_dir=save_dir,
                    filename_prefix=filename_prefix,
                    saved_files=saved_files,
                    content_bytes=base64.b64decode(data_b64),
                    ext="png",
                )
                continue

            image_url = item.get("url")
            if not image_url:
                continue
            data_url = self._decode_data_url(image_url)
            if data_url is not None:
                content_bytes, ext = data_url
                self._write_bytes_to_file(
                    save_dir=save_dir,
                    filename_prefix=filename_prefix,
                    saved_files=saved_files,
                    content_bytes=content_bytes,
                    ext=ext,
                )
                continue
            self._write_bytes_to_file(
                save_dir=save_dir,
                filename_prefix=filename_prefix,
                saved_files=saved_files,
                content_bytes=self._curl_get_bytes_with_retry(
                    url=image_url,
                    max_retries=max_retries,
                    retry_delay=retry_delay,
                ),
                ext=self._guess_ext_from_url(image_url),
            )

        meta = {"model": use_model, "saved_files": saved_files}
        self.Message("assistant", json.dumps(meta, ensure_ascii=False))

        if not saved_files:
            raise ValueError(f"No image data returned. Response: {json.dumps(result, ensure_ascii=False)}")
        return saved_files[0] if len(saved_files) == 1 else saved_files
