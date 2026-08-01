from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from io import BytesIO
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

from src.config_loader import ConfigLoader
from src.alpha_matting_contract import (
    AlphaMattingConfig,
    validate_alpha_matting_provider_config,
)
from src.providers.image_reference_validation import validate_reference_image_bytes
from src.providers.provider_errors import (
    ProviderHttpError,
    ProviderInputError,
    ProviderProtocolError,
    ProviderTransportError,
)


_MAX_OUTPUT_BYTES = 128 * 1024 * 1024


class AlphaMattingProvider:
    def __init__(
        self,
        provider_id: str = "alpha_matting",
        memory_file_path: str | None = None,
        system_prompt: str | None = None,
        internal_memory_enabled: bool = True,
    ):
        del memory_file_path, system_prompt, internal_memory_enabled
        self.provider_id = str(provider_id or "").strip()
        raw_config = ConfigLoader().get_provider_config(self.provider_id)
        self.config = raw_config
        self.contract = validate_alpha_matting_provider_config(self.provider_id, raw_config)

    def Send(self, *_args, **_kwargs):
        raise ProviderInputError(
            "Alpha matting supports matte_image(image_path=..., output_dir=...) only."
        )

    def matte_image(
        self,
        *,
        image_path: str,
        output_dir: str,
        filename_prefix: str = "matted_image",
    ) -> dict:
        source_path = os.path.abspath(str(image_path or "").strip())
        if not source_path or not os.path.isfile(source_path):
            raise ProviderInputError(f"Input image does not exist: {source_path or '<empty>'}")
        try:
            with open(source_path, "rb") as file_obj:
                source_bytes = file_obj.read()
        except OSError as exc:
            raise ProviderInputError(f"Failed to read input image '{source_path}': {exc}") from exc
        source_info = validate_reference_image_bytes(source_bytes, source=source_path)

        health = self._ensure_service_ready()
        output_bytes, headers = self._post_image(
            self.contract,
            source_bytes,
            filename=os.path.basename(source_path),
            mime_type=source_info.mime_type,
        )
        result_info = self._validate_output(output_bytes, headers)
        if (result_info["width"], result_info["height"]) != (source_info.width, source_info.height):
            raise ProviderProtocolError(
                "Alpha-matting output dimensions do not match the input image: "
                f"{result_info['width']}x{result_info['height']} != "
                f"{source_info.width}x{source_info.height}."
            )

        saved_path = self._save_output(output_bytes, output_dir, filename_prefix)
        return {
            "image_path": saved_path,
            "status": "success",
            "provider_id": self.provider_id,
            "model": str(health.get("model_id") or self.contract.model),
            "model_revision": str(health.get("model_revision") or self.contract.model_revision),
            **result_info,
        }

    def _ensure_service_ready(self) -> dict:
        try:
            return self._read_health()
        except ProviderTransportError:
            runtime = self.contract.local_runtime
            if not runtime.managed:
                raise

        process = self._start_managed_runtime()
        deadline = time.monotonic() + self.contract.local_runtime.startup_timeout_ms / 1000
        last_error: ProviderTransportError | None = None
        while time.monotonic() < deadline:
            try:
                return self._read_health()
            except ProviderTransportError as exc:
                last_error = exc
            exit_code = process.poll()
            if exit_code is not None:
                stdout, stderr = process.communicate()
                details = (stderr or stdout or "").strip()
                suffix = f": {details}" if details else ""
                raise ProviderTransportError(
                    f"Managed alpha-matting launcher exited with code {exit_code}{suffix}"
                )
            time.sleep(0.5)
        raise ProviderTransportError(
            "Managed alpha-matting service did not become healthy within "
            f"{self.contract.local_runtime.startup_timeout_ms} ms: {last_error or 'connection failed'}"
        )

    def _start_managed_runtime(self) -> subprocess.Popen:
        runtime = self.contract.local_runtime
        creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0
        try:
            return subprocess.Popen(
                list(runtime.startup_command),
                cwd=runtime.working_directory,
                shell=False,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=creation_flags,
            )
        except OSError as exc:
            raise ProviderTransportError(
                f"Failed to start managed alpha-matting runtime: {exc}"
            ) from exc

    def _read_health(self) -> dict:
        request = Request(self.contract.health_url, method="GET")
        try:
            with urlopen(request, timeout=min(self.contract.timeout_ms / 1000, 10)) as response:
                status = int(response.status)
                body = response.read(64 * 1024 + 1)
        except HTTPError as exc:
            body = exc.read(64 * 1024).decode("utf-8", errors="replace")
            raise ProviderProtocolError(
                f"Alpha-matting health check returned HTTP {exc.code}: {body}"
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise ProviderTransportError(f"Alpha-matting health check failed: {exc}") from exc
        if status != 200:
            raise ProviderTransportError(f"Alpha-matting health check returned HTTP {status}.")
        if len(body) > 64 * 1024:
            raise ProviderProtocolError("Alpha-matting health response is too large.")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ProviderProtocolError("Alpha-matting health response is not valid UTF-8 JSON.") from exc
        if not isinstance(payload, dict):
            raise ProviderProtocolError("Alpha-matting health response must be an object.")
        if payload.get("status") != "ok" or payload.get("service") != "agentpark-alpha-matting":
            raise ProviderProtocolError("Alpha-matting health response identifies an unexpected service.")
        if payload.get("loaded") is not True:
            raise ProviderProtocolError("Alpha-matting service is healthy but its model is not loaded.")
        model_id = str(payload.get("model_id") or "").strip()
        if model_id != self.contract.model:
            raise ProviderProtocolError(
                f"Alpha-matting service loaded model '{model_id}', expected '{self.contract.model}'."
            )
        model_revision = str(payload.get("model_revision") or "").strip()
        if model_revision != self.contract.model_revision:
            raise ProviderProtocolError(
                "Alpha-matting service loaded model revision "
                f"'{model_revision}', expected '{self.contract.model_revision}'."
            )
        return payload

    @staticmethod
    def _post_image(
        contract: AlphaMattingConfig,
        content: bytes,
        *,
        filename: str,
        mime_type: str,
    ) -> tuple[bytes, dict[str, str]]:
        boundary = f"agentpark-{uuid.uuid4().hex}"
        safe_filename = re.sub(r"[^a-zA-Z0-9._-]", "_", filename) or "image"
        prefix = (
            f"--{boundary}\r\n"
            f'Content-Disposition: form-data; name="image"; filename="{safe_filename}"\r\n'
            f"Content-Type: {mime_type}\r\n\r\n"
        ).encode("ascii")
        body = prefix + content + f"\r\n--{boundary}--\r\n".encode("ascii")
        request = Request(
            contract.matting_url,
            data=body,
            method="POST",
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        )
        try:
            with urlopen(request, timeout=contract.timeout_ms / 1000) as response:
                status = int(response.status)
                response_bytes = response.read(_MAX_OUTPUT_BYTES + 1)
                response_headers = {key.lower(): value for key, value in response.headers.items()}
        except HTTPError as exc:
            error_body = exc.read(64 * 1024).decode("utf-8", errors="replace")
            raise ProviderHttpError(
                exc.code,
                error_body,
                message_prefix="Alpha-matting endpoint HTTP",
            ) from exc
        except (URLError, OSError, TimeoutError) as exc:
            raise ProviderTransportError(f"Alpha-matting request failed: {exc}") from exc
        if status != 200:
            raise ProviderHttpError(status, "", message_prefix="Alpha-matting endpoint HTTP")
        if len(response_bytes) > _MAX_OUTPUT_BYTES:
            raise ProviderProtocolError("Alpha-matting PNG response exceeds 128 MB.")
        content_type = response_headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "image/png":
            raise ProviderProtocolError(
                f"Alpha-matting endpoint returned '{content_type or '<missing>'}', expected image/png."
            )
        return response_bytes, response_headers

    @staticmethod
    def _validate_output(content: bytes, headers: dict[str, str]) -> dict:
        try:
            with Image.open(BytesIO(content)) as image:
                image.load()
                if image.format != "PNG" or image.mode != "RGBA":
                    raise ProviderProtocolError(
                        f"Alpha-matting output must be PNG RGBA, got {image.format or 'unknown'} {image.mode}."
                    )
                width, height = image.size
                alpha_min, alpha_max = image.getchannel("A").getextrema()
        except ProviderProtocolError:
            raise
        except (UnidentifiedImageError, OSError, SyntaxError) as exc:
            raise ProviderProtocolError("Alpha-matting output is not a decodable PNG.") from exc
        if alpha_min >= alpha_max:
            raise ProviderProtocolError(
                f"Alpha-matting output has no nontrivial alpha range: {alpha_min}..{alpha_max}."
            )

        expected = {
            "x-image-width": width,
            "x-image-height": height,
            "x-alpha-min": alpha_min,
            "x-alpha-max": alpha_max,
        }
        for name, decoded_value in expected.items():
            raw_value = headers.get(name)
            try:
                header_value = int(raw_value) if raw_value is not None else None
            except ValueError as exc:
                raise ProviderProtocolError(f"Alpha-matting response header {name} is not an integer.") from exc
            if header_value != decoded_value:
                raise ProviderProtocolError(
                    f"Alpha-matting response header {name}={raw_value!r} "
                    f"does not match decoded value {decoded_value}."
                )

        result = {
            "width": width,
            "height": height,
            "alpha_min": alpha_min,
            "alpha_max": alpha_max,
        }
        peak = headers.get("x-cuda-peak-memory-allocated-bytes")
        if peak is not None:
            try:
                result["cuda_peak_memory_allocated_bytes"] = int(peak)
            except ValueError as exc:
                raise ProviderProtocolError(
                    "Alpha-matting CUDA peak-memory header is not an integer."
                ) from exc
            if result["cuda_peak_memory_allocated_bytes"] < 0:
                raise ProviderProtocolError(
                    "Alpha-matting CUDA peak-memory header must not be negative."
                )
        return result

    @staticmethod
    def _save_output(content: bytes, output_dir: str, filename_prefix: str) -> str:
        raw_output_dir = str(output_dir or "").strip()
        if not raw_output_dir:
            raise ProviderInputError("output_dir is required.")
        resolved_dir = os.path.abspath(raw_output_dir)
        prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", str(filename_prefix or "").strip())
        if not prefix:
            raise ProviderInputError("filename_prefix must contain a filename-safe character.")
        os.makedirs(resolved_dir, exist_ok=True)
        destination = os.path.join(resolved_dir, f"{prefix}_{uuid.uuid4().hex}.png")
        temporary = f"{destination}.tmp"
        try:
            with open(temporary, "wb") as file_obj:
                file_obj.write(content)
            os.replace(temporary, destination)
        except OSError as exc:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                pass
            raise ProviderTransportError(f"Failed to save alpha-matting output: {exc}") from exc
        return destination
