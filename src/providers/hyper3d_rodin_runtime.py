import json
import os
import re
import tempfile
import time
import urllib.parse
from datetime import datetime

from src.providers.hyper3d_common import is_hyper3d_remote_url
from src.providers.hyper3d_common import parse_hyper3d_int
from src.providers.hyper3d_common import resolve_hyper3d_enum
from src.providers.hyper3d_runtime_base import Hyper3DRuntimeBase
from src.providers.hyper3d_transport import build_multipart_body
from src.value_parsing import parse_optional_bool_value


class Hyper3DRodinRuntime(Hyper3DRuntimeBase):
    _TERMINAL_STATUSES = {"done", "failed"}
    _DOWNLOAD_NAME_PATTERN = re.compile(r"[^A-Za-z0-9._ -]+")

    def _api_url(self, endpoint):
        endpoint_text = str(endpoint or "").strip("/")
        base_url = self._base_url()
        if base_url.endswith("/rodin") and endpoint_text == "rodin":
            return base_url
        return f"{base_url}/{endpoint_text}"

    def _materialize_image_paths(self, images, temp_dir):
        local_paths: list[str] = []
        for index, uri in enumerate(images or []):
            text = str(uri or "").strip()
            if not text:
                continue
            if is_hyper3d_remote_url(text):
                parsed = urllib.parse.urlparse(text)
                ext = os.path.splitext(parsed.path)[1] or ".jpg"
                temp_path = os.path.join(temp_dir, f"hyper3d_image_{index}{ext}")
                with open(temp_path, "wb") as file_obj:
                    file_obj.write(self._download_bytes(text))
                local_paths.append(temp_path)
                continue
            local_path = os.path.abspath(text[7:] if text.startswith("file://") else text)
            if not os.path.isfile(local_path):
                raise FileNotFoundError(f"Image file not found: {text}")
            local_paths.append(local_path)
        return local_paths

    def _build_fields(
        self,
        *,
        prompt,
        tier,
        use_original_alpha,
        seed,
        geometry_file_format,
        material,
        quality,
        quality_override,
        tapose,
        bbox_condition,
        mesh_mode,
        addons,
        preview_render,
        hd_texture,
    ):
        resolved_mesh_mode = resolve_hyper3d_enum("mesh_mode", mesh_mode, {"Raw", "Quad"})
        fields: list[tuple[str, object]] = [("tier", tier or self.config.get("tier") or "Gen-2")]
        if prompt:
            fields.append(("prompt", prompt))

        for name, value in (
            ("use_original_alpha", parse_optional_bool_value("use_original_alpha", use_original_alpha)),
            ("TAPose", parse_optional_bool_value("TAPose", tapose)),
            ("preview_render", parse_optional_bool_value("preview_render", preview_render)),
            ("hd_texture", parse_optional_bool_value("hd_texture", hd_texture)),
        ):
            if value is not None:
                fields.append((name, "true" if value else "false"))

        resolved_seed = parse_hyper3d_int("seed", seed, minimum=0, maximum=65535)
        if resolved_seed is not None:
            fields.append(("seed", resolved_seed))

        enum_values = (
            ("geometry_file_format", geometry_file_format, {"glb", "usdz", "fbx", "obj", "stl"}),
            ("material", material, {"PBR", "Shaded", "All", "None"}),
            ("quality", quality, {"high", "medium", "low", "extra-low"}),
        )
        for name, value, allowed in enum_values:
            resolved = resolve_hyper3d_enum(name, value, allowed)
            if resolved is not None:
                fields.append((name, resolved))

        if quality_override is not None and quality_override != "":
            max_count = 200000 if resolved_mesh_mode == "Quad" else 1000000
            min_count = 1000 if resolved_mesh_mode == "Quad" else 500
            fields.append(
                (
                    "quality_override",
                    parse_hyper3d_int("quality_override", quality_override, minimum=min_count, maximum=max_count),
                )
            )

        if isinstance(bbox_condition, list):
            parsed_bbox = bbox_condition
        else:
            parsed_bbox = []
        if parsed_bbox:
            if len(parsed_bbox) != 3:
                raise ValueError("bbox_condition must contain exactly 3 integers.")
            fields.append(("bbox_condition", json.dumps([int(item) for item in parsed_bbox])))

        if resolved_mesh_mode is not None:
            fields.append(("mesh_mode", resolved_mesh_mode))

        addon_text = str(addons or "").strip()
        if addon_text:
            if addon_text != "HighPack":
                raise ValueError("addons must be empty or HighPack.")
            fields.append(("addons", json.dumps([addon_text])))

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
                raise TimeoutError(f"Hyper3D task timed out after {max_wait_sec:.0f}s. subscription_key={subscription_key}")
            time.sleep(poll_interval_sec)

    def _sanitize_download_name(self, name, index):
        raw = os.path.basename(str(name or "").strip())
        clean = self._DOWNLOAD_NAME_PATTERN.sub("_", raw).strip(" .")
        return clean or f"hyper3d_result_{index}"

    def _save_downloads(self, items, filename_prefix):
        save_dir = os.path.dirname(self.current_memory_path)
        os.makedirs(save_dir, exist_ok=True)
        agent_id = os.path.splitext(os.path.basename(self.current_memory_path))[0]
        prefix = str(filename_prefix or "generated_model").strip() or "generated_model"
        if not prefix.startswith(f"{agent_id}_"):
            prefix = f"{agent_id}_{prefix}"

        saved_files: list[str] = []
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        used: set[str] = set()
        for index, item in enumerate(items or []):
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "").strip()
            if not url:
                continue
            name = self._sanitize_download_name(item.get("name"), index)
            filename = f"{prefix}_{ts}_{index}_{name}"
            if "." not in os.path.basename(filename):
                parsed = urllib.parse.urlparse(url)
                ext = os.path.splitext(parsed.path)[1]
                if ext:
                    filename += ext
            while filename.lower() in used:
                filename = f"{prefix}_{ts}_{index}_{uuid.uuid4().hex[:6]}_{name}"
            used.add(filename.lower())
            path = os.path.join(save_dir, filename)
            with open(path, "wb") as file_obj:
                file_obj.write(self._download_bytes(url))
            saved_files.append(path)
        return saved_files

    def generate_3d_model(
        self,
        *,
        prompt="",
        images=None,
        filename_prefix="generated_model",
        tier=None,
        use_original_alpha=None,
        seed=None,
        geometry_file_format=None,
        material=None,
        quality=None,
        quality_override=None,
        tapose=None,
        bbox_condition=None,
        mesh_mode=None,
        addons=None,
        preview_render=None,
        hd_texture=None,
    ):
        read_provider_config = getattr(self.host, "_read_provider_config_from_file", None)
        if callable(read_provider_config):
            self.config = read_provider_config()

        if not self.config.get("apiKey"):
            raise ValueError("Hyper3D provider requires apiKey.")

        poll_interval_sec = self._resolve_poll_interval_seconds(
            "pollIntervalSec",
            "modelGenerationPollIntervalSec",
            default=5,
        )
        max_wait_sec = self._resolve_max_wait_seconds(
            "maxWaitSec",
            "modelGenerationMaxWaitSec",
            default=1800,
        )

        with tempfile.TemporaryDirectory(prefix="aitools_hyper3d_") as temp_dir:
            image_paths = self._materialize_image_paths(images or [], temp_dir)
            if not prompt and not image_paths:
                raise ValueError("Hyper3D Rodin requires a prompt or images.")

            fields = self._build_fields(
                prompt=prompt,
                tier=tier,
                use_original_alpha=use_original_alpha,
                seed=seed,
                geometry_file_format=geometry_file_format,
                material=material,
                quality=quality,
                quality_override=quality_override,
                tapose=tapose,
                bbox_condition=bbox_condition,
                mesh_mode=mesh_mode,
                addons=addons,
                preview_render=preview_render,
                hd_texture=hd_texture,
            )
            body, content_type = build_multipart_body(fields, [("images", path) for path in image_paths])
            create_result = self._request_json(
                url=self._api_url("rodin"),
                headers=self._headers(multipart_content_type=content_type),
                body=body,
            )

        task_uuid = str(create_result.get("uuid") or "").strip() if isinstance(create_result, dict) else ""
        jobs = create_result.get("jobs") if isinstance(create_result, dict) else {}
        subscription_key = str((jobs or {}).get("subscription_key") or "").strip() if isinstance(jobs, dict) else ""
        if not task_uuid or not subscription_key:
            raise ValueError(f"Unexpected Hyper3D create response: {json.dumps(create_result, ensure_ascii=False)}")

        status_result = self._poll_status(
            subscription_key,
            poll_interval_sec=poll_interval_sec,
            max_wait_sec=max_wait_sec,
        )
        failed_jobs = [
            job for job in status_result.get("jobs", [])
            if isinstance(job, dict) and str(job.get("status") or "").strip().lower() == "failed"
        ]
        if failed_jobs:
            raise RuntimeError(f"Hyper3D task failed: {json.dumps(status_result, ensure_ascii=False)}")

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
            raise ValueError(f"Hyper3D download response contained no downloadable files: {json.dumps(download_result, ensure_ascii=False)}")

        result = {
            "response": f"3D model generated successfully: {', '.join(saved_files)}",
            "saved_files": saved_files,
            "task_uuid": task_uuid,
            "subscription_key": subscription_key,
            "status": "success",
            "download_items": download_items,
        }
        self.Message("assistant", json.dumps(result, ensure_ascii=False))
        return result
