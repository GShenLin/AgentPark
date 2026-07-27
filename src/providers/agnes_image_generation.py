import base64
import json
import os
import urllib.parse
from datetime import datetime

from src.providers.agnes_image_generation_contract import build_agnes_image_payload
from src.providers.image_reference_validation import validate_reference_image_bytes
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.service_host import HostBoundService


class AgnesImageGeneration(ProviderRuntimeEventMixin, HostBoundService):
    """Agnes image generation, response decoding, and local persistence."""

    def generate_image(
        self,
        prompt,
        filename_prefix="generated_image",
        size=None,
        response_format="url",
        image=None,
        **_unsupported_options,
    ):
        read_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_config):
            self.config = read_config()

        model = str(self.config.get("model") or "").strip()
        if not model:
            raise ValueError("Agnes image model is required for image generation.")
        payload = build_agnes_image_payload(
            model=model,
            prompt=prompt,
            size=size or self.config.get("imageSize") or "1024x1024",
            response_format=response_format,
            image=self._prepare_reference_images(image),
        )
        base_url = self.config["baseUrl"].rstrip("/")
        url = base_url if base_url.endswith("/images/generations") else f"{base_url}/images/generations"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.config['apiKey']}",
        }
        self._emit_provider_runtime_notice(
            message=f"Generating image with model {model}.",
            stage="image_generation_start",
        )
        result = self._post_json_with_retry(
            endpoint="images/generations",
            url=url,
            headers=headers,
            payload_json=json.dumps(payload, ensure_ascii=False),
            max_retries=int(self.config.get("imageGenerationMaxRetries", 0)),
            retry_delay=float(self.config.get("imageGenerationRetryDelaySec", 1)),
            timeout_ms=int(self.config.get("imageGenerationTimeoutMs", 180000)),
        )
        paths = self._persist_results(
            result,
            filename_prefix=filename_prefix,
            response_format=response_format,
        )
        self.Message("assistant", json.dumps({
            "created": result.get("created"),
            "model": result.get("model") or model,
            "saved_files": paths,
        }, ensure_ascii=False))
        return paths[0] if len(paths) == 1 else paths

    def _persist_results(self, result, *, filename_prefix, response_format):
        data_items = result.get("data") if isinstance(result, dict) else None
        if not isinstance(data_items, list) or not data_items:
            raise ValueError(f"Unexpected Agnes image response: {json.dumps(result, ensure_ascii=False)}")

        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        if not filename_prefix.startswith(f"{agent_id}_"):
            filename_prefix = f"{agent_id}_{filename_prefix}"

        paths = []
        for item in data_items:
            if not isinstance(item, dict):
                continue
            encoded = str(item.get("b64_json") or "").strip()
            image_url = str(item.get("url") or "").strip()
            if encoded:
                content = base64.b64decode(encoded, validate=True)
                extension = "png"
            elif image_url:
                content = self._curl_get_bytes_with_retry(
                    url=image_url,
                    max_retries=int(self.config.get("maxRetries", 2)),
                    retry_delay=float(self.config.get("retryDelaySec", 1)),
                )
                extension = self._extension_from_url(image_url)
            else:
                continue
            validate_reference_image_bytes(content, source="Agnes generated image")
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            path = os.path.join(
                save_dir,
                f"{filename_prefix}_{timestamp}_{len(paths) + 1}.{extension}",
            )
            with open(path, "wb") as output:
                output.write(content)
            paths.append(path)
        if not paths:
            raise ValueError(
                f"Agnes returned no image data for {response_format}: "
                f"{json.dumps(result, ensure_ascii=False)}"
            )
        return paths

    def _prepare_reference_images(self, image):
        if image is None:
            return None
        values = image if isinstance(image, (list, tuple)) else [image]
        prepared = []
        for raw in values:
            value = str(raw or "").strip()
            if not value:
                continue
            parsed = urllib.parse.urlparse(value)
            if parsed.scheme in {"http", "https"} and parsed.netloc:
                prepared.append(value)
                continue
            if value.startswith("data:image/") and ";base64," in value:
                _, encoded = value.split(",", 1)
                validate_reference_image_bytes(
                    base64.b64decode(encoded, validate=True),
                    source="Agnes reference image data URL",
                )
                prepared.append(value)
                continue
            if not os.path.isfile(value):
                raise ValueError(f"Unsupported Agnes reference image URI: {value}")
            with open(value, "rb") as source:
                content = source.read()
            validate_reference_image_bytes(content, source="Agnes local reference image")
            mime = "image/png" if value.lower().endswith(".png") else "image/jpeg"
            prepared.append(f"data:{mime};base64,{base64.b64encode(content).decode('ascii')}")
        return prepared or None

    @staticmethod
    def _extension_from_url(url):
        extension = os.path.splitext(urllib.parse.urlparse(url).path)[1].lower().lstrip(".")
        return extension if extension in {"png", "jpg", "jpeg", "webp"} else "png"
