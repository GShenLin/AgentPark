import json
import os
import re
import tempfile
import time
import urllib.parse
import uuid
from datetime import datetime

from src.providers.hyper3d_common import is_hyper3d_remote_url
from src.providers.hyper3d_common import parse_hyper3d_int
from src.providers.hyper3d_common import resolve_hyper3d_enum
from src.providers.hyper3d_runtime_base import Hyper3DRuntimeBase
from src.providers.hyper3d_transport import build_multipart_body
from src.value_parsing import parse_optional_float_value


class Hyper3DTextureRuntime(Hyper3DRuntimeBase):
    _TERMINAL_STATUSES = {"done", "failed"}
    _DOWNLOAD_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._ -]+")
    _MAX_MODEL_BYTES = 10 * 1024 * 1024

    def _materialize_path(self, uri, temp_dir, *, prefix, default_ext):
        text = str(uri or "").strip()
        if not text:
            raise ValueError(f"{prefix} path is required.")
        if is_hyper3d_remote_url(text):
            parsed = urllib.parse.urlparse(text)
            ext = os.path.splitext(parsed.path)[1] or default_ext
            temp_path = os.path.join(temp_dir, f"{prefix}{ext}")
            with open(temp_path, "wb") as file_obj:
                file_obj.write(self._download_bytes(text))
            return temp_path
        local_path = os.path.abspath(text[7:] if text.startswith("file://") else text)
        if not os.path.isfile(local_path):
            raise FileNotFoundError(f"File not found: {text}")
        return local_path

    def _validate_model_size(self, model_path):
        size = os.path.getsize(model_path)
        if size > self._MAX_MODEL_BYTES:
            raise ValueError("Hyper3D texture generation model file must be 10MB or smaller.")

    def _build_fields(self, *, prompt, seed, reference_scale, geometry_file_format, material, resolution):
        fields: list[tuple[str, object]] = []
        if prompt:
            fields.append(("prompt", prompt))
        parsed_seed = parse_hyper3d_int("seed", seed, minimum=0, maximum=65535)
        if parsed_seed is not None:
            fields.append(("seed", parsed_seed))
        parsed_reference_scale = parse_optional_float_value(
            "reference_scale",
            reference_scale,
            minimum_exclusive=0,
        )
        if parsed_reference_scale is not None:
            fields.append(("reference_scale", parsed_reference_scale))
        for name, value, allowed in (
            ("geometry_file_format", geometry_file_format, {"glb", "usdz", "fbx", "obj", "stl"}),
            ("material", material, {"PBR", "Shaded"}),
            ("resolution", resolution, {"Basic", "High"}),
        ):
            resolved = resolve_hyper3d_enum(name, value, allowed)
            if resolved is not None:
                fields.append((name, resolved))
        return fields

    def _poll_status(self, subscription_key, *, poll_interval_sec, max_wait_sec):
        started = time.monotonic()
        while True:
            status_result = self._request_json(
                url=self._api_url("status"),
                headers=self._headers(json_content=True),
                body=json.dumps({"subscription_key": subscription_key}, ensure_ascii=False).encode("utf-8"),
            )
            jobs = status_result.get("jobs") if isinstance(status_result, dict) else None
            if not isinstance(jobs, list):
                raise ValueError(f"Unexpected Hyper3D status response: {json.dumps(status_result, ensure_ascii=False)}")
            statuses = {str((job or {}).get("status") or "").strip().lower() for job in jobs if isinstance(job, dict)}
            if statuses and statuses.issubset(self._TERMINAL_STATUSES):
                return status_result
            if max_wait_sec is not None and (time.monotonic() - started) >= max_wait_sec:
                raise TimeoutError(f"Hyper3D texture task timed out after {max_wait_sec:.0f}s.")
            time.sleep(poll_interval_sec)

    def _save_downloads(self, items, filename_prefix):
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        prefix = str(filename_prefix or "generated_textured_model").strip() or "generated_textured_model"
        if not prefix.startswith(f"{agent_id}_"):
            prefix = f"{agent_id}_{prefix}"
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        saved_files: list[str] = []
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            raw_name = os.path.basename(str(item.get("name") or "").strip())
            clean_name = self._DOWNLOAD_NAME_PATTERN.sub("_", raw_name).strip(" .") or f"texture_result_{index}"
            filename = f"{prefix}_{ts}_{index}_{clean_name}"
            if "." not in os.path.basename(filename):
                ext = os.path.splitext(urllib.parse.urlparse(url).path)[1]
                if ext:
                    filename += ext
            path = os.path.join(save_dir, filename)
            while os.path.exists(path):
                path = os.path.join(save_dir, f"{prefix}_{ts}_{index}_{uuid.uuid4().hex[:6]}_{clean_name}")
            with open(path, "wb") as file_obj:
                file_obj.write(self._download_bytes(url))
            saved_files.append(path)
        return saved_files

    def generate_3d_texture(
        self,
        *,
        model_path,
        image_path,
        prompt="",
        filename_prefix="generated_textured_model",
        seed=None,
        reference_scale=None,
        geometry_file_format=None,
        material=None,
        resolution=None,
    ):
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()
        if not self.config.get("apiKey"):
            raise ValueError("Hyper3D provider requires apiKey.")

        poll_interval_sec = self._resolve_poll_interval_seconds(
            "texturePollIntervalSec",
            "pollIntervalSec",
            default=5,
        )
        max_wait_sec = self._resolve_max_wait_seconds(
            "textureMaxWaitSec",
            "maxWaitSec",
            default=1800,
        )

        with tempfile.TemporaryDirectory(prefix="agentpark_hyper3d_texture_") as temp_dir:
            local_model = self._materialize_path(model_path, temp_dir, prefix="model", default_ext=".obj")
            local_image = self._materialize_path(image_path, temp_dir, prefix="image", default_ext=".jpg")
            self._validate_model_size(local_model)
            fields = self._build_fields(
                prompt=prompt,
                seed=seed,
                reference_scale=reference_scale,
                geometry_file_format=geometry_file_format,
                material=material,
                resolution=resolution,
            )
            body, content_type = build_multipart_body(fields, [("image", local_image), ("model", local_model)])
            create_result = self._request_json(
                url=self._api_url("rodin_texture_only"),
                headers=self._headers(multipart_content_type=content_type),
                body=body,
            )

        task_uuid = str(create_result.get("uuid") or "").strip() if isinstance(create_result, dict) else ""
        jobs = create_result.get("jobs") if isinstance(create_result, dict) else {}
        subscription_key = str((jobs or {}).get("subscription_key") or "").strip() if isinstance(jobs, dict) else ""
        if not task_uuid or not subscription_key:
            raise ValueError(f"Unexpected Hyper3D texture response: {json.dumps(create_result, ensure_ascii=False)}")

        status_result = self._poll_status(subscription_key, poll_interval_sec=poll_interval_sec, max_wait_sec=max_wait_sec)
        failed_jobs = [
            job for job in status_result.get("jobs", [])
            if isinstance(job, dict) and str(job.get("status") or "").strip().lower() == "failed"
        ]
        if failed_jobs:
            raise RuntimeError(f"Hyper3D texture task failed: {json.dumps(status_result, ensure_ascii=False)}")

        download_result = self._request_json(
            url=self._api_url("download"),
            headers=self._headers(json_content=True),
            body=json.dumps({"task_uuid": task_uuid}, ensure_ascii=False).encode("utf-8"),
        )
        download_items = download_result.get("list") if isinstance(download_result, dict) else None
        if not isinstance(download_items, list):
            raise ValueError(f"Unexpected Hyper3D download response: {json.dumps(download_result, ensure_ascii=False)}")
        saved_files = self._save_downloads(download_items, filename_prefix)
        if not saved_files:
            raise ValueError(f"Hyper3D texture response contained no downloadable files: {json.dumps(download_result, ensure_ascii=False)}")

        result = {
            "response": f"3D texture generated successfully: {', '.join(saved_files)}",
            "saved_files": saved_files,
            "task_uuid": task_uuid,
            "subscription_key": subscription_key,
            "status": "success",
            "download_items": download_items,
        }
        self.Message("assistant", json.dumps(result, ensure_ascii=False))
        return result
