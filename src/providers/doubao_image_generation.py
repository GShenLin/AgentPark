import base64
import json
import os
import urllib.parse
from datetime import datetime

from src.providers.curl_transport import CurlResponse
from src.providers.doubao_image_generation_contract import build_seedream_image_payload
from src.providers.doubao_image_stream import merge_seedream_stream_events
from src.providers.image_reference_validation import validate_reference_image_bytes
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.service_host import HostBoundService


class DoubaoImageGeneration(ProviderRuntimeEventMixin, HostBoundService):
    def generate_image(
        self,
        prompt,
        filename_prefix="generated_image",
        size=None,
        response_format="url",
        watermark=True,
        image=None,
        sequential_image_generation=None,
        max_images=None,
        stream=False,
        optimize_prompt_mode=None,
        output_format=None,
        tools=None,
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
        use_model = self.config.get("model")
        if not use_model:
            raise ValueError("DouBao image model is required for image generation.")
        use_size = size or self.config.get("imageSize") or "2K"

        endpoint_suffix = "/images/generations"
        if base_url.endswith(endpoint_suffix):
            url = base_url
        else:
            url = f"{base_url}{endpoint_suffix}"

        self._emit_provider_runtime_notice(
            message=f"Generating image with model {use_model}.",
            stage="image_generation_start",
        )

        payload = build_seedream_image_payload(
            model=use_model,
            prompt=prompt,
            size=use_size,
            response_format=response_format,
            watermark=watermark,
            image=self._prepare_reference_images(image),
            optimize_prompt_mode=optimize_prompt_mode,
            output_format=output_format,
            sequential_image_generation=sequential_image_generation,
            max_images=max_images,
            stream=stream,
            tools=tools,
        )

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }

        payload_json = json.dumps(payload, ensure_ascii=False)
        max_retries = int(self.config.get("imageGenerationMaxRetries", 0))
        retry_delay = float(self.config.get("imageGenerationRetryDelaySec", 1))
        timeout_ms = int(self.config.get("imageGenerationTimeoutMs", 180000))
        result = self._request_images(
            url=url,
            headers=headers,
            payload_json=payload_json,
            stream=bool(payload.get("stream")),
            max_retries=max_retries,
            retry_delay=retry_delay,
            timeout_ms=timeout_ms,
        )

        data_items = result.get("data") or []
        if not data_items:
            error = result.get("error") if isinstance(result.get("error"), dict) else {}
            if error:
                code = str(error.get("code") or "image_generation_error")
                message = str(error.get("message") or "image generation failed")
                raise ValueError(f"{code}: {message}")
            raise ValueError(f"Unexpected response format: {json.dumps(result, ensure_ascii=False)}")

        saved_files = []
        item_errors = []

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
            return str(output_format or "jpeg").strip().lower() or "jpeg"

        def _write_bytes_to_file(content_bytes, ext):
            normalized_ext = str(ext or "").strip().lower()
            if normalized_ext == "jpg":
                normalized_ext = "jpeg"
            if normalized_ext not in {"jpeg", "png"}:
                raise ValueError(f"Unexpected generated image output format: {normalized_ext or '<empty>'}")
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"{filename_prefix}_{ts}_{len(saved_files) + 1}.{normalized_ext}"
            file_path = os.path.join(save_dir, filename)
            with open(file_path, "wb") as f:
                f.write(content_bytes)
            saved_files.append(file_path)

        for item in data_items:
            if not isinstance(item, dict):
                continue
            item_error = item.get("error") if isinstance(item.get("error"), dict) else None
            if item_error:
                item_errors.append({
                    "code": str(item_error.get("code") or "image_generation_error"),
                    "message": str(item_error.get("message") or "image generation failed"),
                })
                continue
            if response_format == "b64_json" or "b64_json" in item:
                data_b64 = item.get("b64_json")
                if not data_b64:
                    continue
                ext = str(item.get("output_format") or output_format or "jpeg").strip().lower()
                _write_bytes_to_file(base64.b64decode(data_b64, validate=True), ext)
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
            "created": result.get("created"),
            "model": result.get("model") or use_model,
            "saved_files": saved_files,
            "errors": item_errors,
            "tools": result.get("tools") or [],
            "usage": result.get("usage") or {},
        }
        self.Message("assistant", json.dumps(meta, ensure_ascii=False))

        if not saved_files:
            raise ValueError(f"No image data returned. Response: {json.dumps(result, ensure_ascii=False)}")

        return saved_files[0] if len(saved_files) == 1 else saved_files

    def _request_images(
        self,
        *,
        url,
        headers,
        payload_json,
        stream,
        max_retries,
        retry_delay,
        timeout_ms=None,
    ):
        request_timeout_ms = int(
            self.config.get("imageGenerationTimeoutMs", 180000)
            if timeout_ms is None
            else timeout_ms
        )
        if request_timeout_ms <= 0:
            raise ValueError("imageGenerationTimeoutMs must be greater than zero.")
        if not stream:
            return self._post_json_with_retry(
                endpoint="images/generations",
                url=url,
                headers=headers,
                payload_json=payload_json,
                max_retries=max_retries,
                retry_delay=retry_delay,
                timeout_ms=request_timeout_ms,
            )

        timeout = request_timeout_ms / 1000
        events = []
        response_status = None
        for item in self._curl_post_sse_raw_lines(
            url=url,
            headers=headers,
            payload_json=payload_json,
            timeout_sec=timeout,
            marker="__DOUBAO_IMAGE_HTTP_CODE__:",
        ):
            if isinstance(item, CurlResponse):
                response_status = item.status_code
                continue
            if item == "[DONE]":
                continue
            try:
                event = json.loads(item)
            except json.JSONDecodeError as exc:
                raise ValueError(f"Invalid image generation SSE event JSON: {exc}") from exc
            if not isinstance(event, dict):
                raise ValueError("Image generation SSE event must be a JSON object")
            events.append(event)
        if response_status != 200:
            raise RuntimeError(f"Image generation stream failed with HTTP {response_status or 'unknown'}")
        return merge_seedream_stream_events(events)

    def _prepare_reference_images(self, image):
        if image is None:
            return None
        raw_values = image if isinstance(image, (list, tuple)) else [image]
        prepared = []
        for raw_value in raw_values:
            value = str(raw_value or "").strip()
            if not value:
                continue
            parsed = urllib.parse.urlparse(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                content = self._curl_get_bytes_with_retry(
                    url=value,
                    max_retries=int(self.config.get("maxRetries", 2)),
                    retry_delay=float(self.config.get("retryDelaySec", 1)),
                )
                validate_reference_image_bytes(content, source="remote reference image")
                prepared.append(value)
                continue
            if value.startswith("data:image/") and ";base64," in value:
                header, encoded = value.split(",", 1)
                media_type = header.removeprefix("data:").split(";", 1)[0]
                if media_type != media_type.lower():
                    raise ValueError("Reference image data URL media type must be lowercase")
                content = base64.b64decode(encoded, validate=True)
                validate_reference_image_bytes(
                    content,
                    declared_mime_type=media_type,
                    source="reference image data URL",
                )
                prepared.append(value)
                continue
            if not os.path.isfile(value):
                raise ValueError(f"Unsupported reference image URI: {value}")
            with open(value, "rb") as image_file:
                content = image_file.read()
            image_info = validate_reference_image_bytes(content, source=f"reference image '{value}'")
            encoded = base64.b64encode(content).decode("ascii")
            prepared.append(f"data:{image_info.mime_type};base64,{encoded}")
        return prepared or None
