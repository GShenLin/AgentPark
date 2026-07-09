import base64
import json
import mimetypes
import os
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from src.providers.provider_pressure import acquire_provider_pressure
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.service_host import HostBoundService


class GeminiImageGeneration(ProviderRuntimeEventMixin, HostBoundService):
    def generate_image(
        self,
        prompt,
        model=None,
        filename_prefix="generated_image",
        image=None,
        aspect_ratio=None,
        image_size=None,
        response_format=None,
        watermark=None,
        size=None,
    ):
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        _ = response_format
        _ = watermark
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)

        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        if not filename_prefix.startswith(f"{agent_id}_"):
            filename_prefix = f"{agent_id}_{filename_prefix}"

        base_url = self.config["baseUrl"].rstrip("/")
        use_model = model or self.config.get("model")
        if not use_model:
            raise ValueError("Gemini model is required for image generation.")

        url = f"{base_url}/models/{use_model}:generateContent"
        parts = [{"text": str(prompt)}]
        parts.extend(self._build_image_input_parts(image))

        generation_config = {"responseModalities": ["TEXT", "IMAGE"]}
        image_config = {}
        if aspect_ratio:
            image_config["aspectRatio"] = str(aspect_ratio)
        final_image_size = image_size or size
        if final_image_size:
            image_config["imageSize"] = str(final_image_size)
        if image_config:
            generation_config["imageConfig"] = image_config

        payload = {
            "contents": [
                {
                    "role": "user",
                    "parts": parts,
                }
            ],
            "generationConfig": generation_config,
        }
        headers = {
            "Content-Type": "application/json",
            "x-goog-api-key": self.config["apiKey"],
        }
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers=headers,
            method="POST",
        )

        max_retries = int(self.config.get("maxRetries", 2))
        retry_delay = float(self.config.get("retryDelaySec", 1))
        timeout = self.config.get("timeoutMs", 60000) / 1000

        last_error = None
        for attempt in range(max_retries + 1):
            try:
                with acquire_provider_pressure(self):
                    with urllib.request.urlopen(req, timeout=timeout) as response:
                        response_data = response.read().decode("utf-8")
                        if response.status != 200:
                            last_error = f"Error: {response.status} - {response_data}"
                            break

                result = json.loads(response_data)
                candidates = result.get("candidates") or []
                if not candidates:
                    raise ValueError(f"Unexpected response format: {response_data}")

                content = candidates[0].get("content") or {}
                parts = content.get("parts") or []
                saved_files = []
                text_parts = []
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    if "text" in part and part["text"] is not None:
                        text_parts.append(str(part["text"]))

                    inline = part.get("inlineData") or part.get("inline_data")
                    if isinstance(inline, dict):
                        mime_type = inline.get("mimeType") or inline.get("mime_type") or "image/png"
                        data_b64 = inline.get("data")
                        if not data_b64:
                            continue

                        ext = "png"
                        if isinstance(mime_type, str) and "/" in mime_type:
                            ext = mime_type.split("/")[-1].strip() or "png"

                        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                        filename = f"{filename_prefix}_{ts}_{len(saved_files) + 1}.{ext}"
                        file_path = os.path.join(save_dir, filename)
                        with open(file_path, "wb") as f:
                            f.write(base64.b64decode(data_b64))
                        saved_files.append(file_path)

                meta = {
                    "model": use_model,
                    "saved_files": saved_files,
                }
                if text_parts:
                    meta["text"] = "".join(text_parts).strip()

                self.Message("assistant", json.dumps(meta, ensure_ascii=False))
                if not saved_files:
                    raise ValueError(f"No image data returned. Response: {response_data}")

                result_path = saved_files[0] if len(saved_files) == 1 else saved_files
                return {
                    "image_path": result_path,
                    "action": "inspect_image",
                    "status": "success",
                }
            except urllib.error.HTTPError as e:
                error_content = e.read().decode("utf-8")
                last_error = f"HTTP Error: {e.code} - {error_content}"
            except Exception as e:
                last_error = str(e)

            if attempt < max_retries:
                self._emit_retry_notice(
                    error=last_error,
                    delay=retry_delay,
                    stage="gemini_image_generation_retry",
                )
                time.sleep(retry_delay + random.uniform(0, 0.5))
                retry_delay *= 2
                continue

        raise RuntimeError(last_error or "Unknown error during image generation.")

    @staticmethod
    def _iter_image_refs(image):
        if image is None:
            return []
        if isinstance(image, list):
            return [str(item).strip() for item in image if str(item).strip()]
        text = str(image or "").strip()
        if not text:
            return []
        if text.startswith("["):
            try:
                parsed = json.loads(text)
            except Exception:
                parsed = None
            if isinstance(parsed, list):
                return [str(item).strip() for item in parsed if str(item).strip()]
        return [text]

    @staticmethod
    def _split_data_url(value: str):
        if not value.startswith("data:") or "," not in value:
            return None
        header, data = value.split(",", 1)
        mime = header[5:].split(";", 1)[0].strip() or "image/png"
        return mime, data.strip()

    @staticmethod
    def _is_http_url(value: str) -> bool:
        try:
            parsed = urllib.parse.urlparse(value)
        except Exception:
            return False
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    def _read_remote_image_part(self, url: str):
        timeout = self.config.get("timeoutMs", 60000) / 1000
        with acquire_provider_pressure(self):
            with urllib.request.urlopen(url, timeout=max(1, float(timeout or 60))) as response:
                raw = response.read()
                mime_type = response.headers.get_content_type() or mimetypes.guess_type(url)[0] or "image/png"
        if not raw:
            raise ValueError(f"reference image URL returned no data: {url}")
        data_b64 = base64.b64encode(raw).decode("utf-8")
        return {"inline_data": {"mime_type": mime_type, "data": data_b64}}

    def _build_image_input_parts(self, image):
        parts = []
        for ref in self._iter_image_refs(image):
            data_url = self._split_data_url(ref)
            if data_url:
                mime_type, data_b64 = data_url
                parts.append({"inline_data": {"mime_type": mime_type, "data": data_b64}})
                continue
            if os.path.isfile(ref):
                mime_type = mimetypes.guess_type(ref)[0] or "image/png"
                with open(ref, "rb") as img_file:
                    data_b64 = base64.b64encode(img_file.read()).decode("utf-8")
                parts.append({"inline_data": {"mime_type": mime_type, "data": data_b64}})
                continue
            if self._is_http_url(ref):
                parts.append(self._read_remote_image_part(ref))
                continue
            raise ValueError(f"Unsupported reference image URI: {ref}")
        return parts
