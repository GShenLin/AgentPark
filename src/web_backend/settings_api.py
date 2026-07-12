from __future__ import annotations

import json
import os
import subprocess

from fastapi import File, Form, HTTPException, UploadFile

from src import workspace_settings
from src.companion_paths import companion_node_config_path
from src.config_loader import ConfigLoader
from src.file_transaction import atomic_write_text
from src.provider_limit_schema import read_provider_limit_file
from src.providers.provider_pressure import get_provider_pressure_manager
from src.runtime_events.event_config_store import event_config_path, load_or_create_event_config
from src.web_backend.theme_settings import (
    active_theme_preset_id,
    list_theme_presets,
    load_or_create_theme_config,
    load_theme_preset,
    save_theme_asset,
    save_theme_preset,
    theme_config_path,
    theme_image_response,
    validate_theme_config,
)
from src.tool.tool_stats_store import (
    clear_tool_stats as clear_tool_stats_store,
    load_recent_tool_call_stats,
    load_tool_stats_summary,
)

from .domain_base import DomainBase
from . import runtime_paths


SETTINGS_SECTIONS = {
    "module-provider": {
        "label": "moduleProvider",
        "filename": "moduleProvider.json",
    },
    "defaults": {
        "label": "Default settings",
        "filename": "config.json",
    },
    "companion": {
        "label": "Companion",
        "filename": "config.json",
    },
    "events": {
        "label": "Runtime Events",
        "filename": "events.json",
    },
    "theme": {
        "label": "Theme",
        "filename": "theme.json",
    },
}


class SettingsApiDomain(DomainBase):
    def _delete_operational_memory_script_path(self) -> str:
        return os.path.join(workspace_settings.get_workspace_root(), "delete_operational_memory.bat")

    def _section_meta(self, section: str) -> dict:
        safe_section = str(section or "").strip()
        meta = SETTINGS_SECTIONS.get(safe_section)
        if meta is None:
            raise HTTPException(status_code=404, detail=f"unknown settings section: {safe_section}")
        return {"id": safe_section, **meta}

    def _settings_path(self, section: str) -> str:
        if section == "module-provider":
            explicit_path = str(os.environ.get(ConfigLoader.CONFIG_PATH_ENV) or "").strip()
            if explicit_path:
                return os.path.abspath(explicit_path)
            return os.path.join(workspace_settings.get_workspace_root(), "config", "moduleProvider.json")
        if section == "defaults":
            explicit_path = str(os.environ.get(ConfigLoader.CONFIG_PATH_ENV) or "").strip()
            if explicit_path:
                return os.path.join(os.path.dirname(os.path.abspath(explicit_path)), "config.json")
            return workspace_settings.get_workspace_config_path()
        if section == "companion":
            return companion_node_config_path(runtime_paths._get_graphs_dir())
        if section == "events":
            return event_config_path()
        if section == "theme":
            return theme_config_path()
        raise HTTPException(status_code=404, detail=f"unknown settings section: {section}")

    def _read_payload(self, path: str, section: str) -> tuple[str, dict, list[str]]:
        if not os.path.isfile(path):
            if section == "events":
                payload = load_or_create_event_config()
                return json.dumps(payload, ensure_ascii=False, indent=2) + "\n", payload, []
            if section == "theme":
                payload = load_or_create_theme_config()
                return json.dumps(payload, ensure_ascii=False, indent=2) + "\n", payload, []
            raise HTTPException(status_code=404, detail=f"{section} settings file not found: {path}")
        try:
            with open(path, "r", encoding="utf-8") as handle:
                content = handle.read()
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=500, detail=f"{section} settings JSON is invalid: {exc}") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to read {section} settings: {exc}") from exc
        warnings: list[str] = []
        if section == "events":
            if not isinstance(payload, dict):
                raise HTTPException(status_code=400, detail="events settings must be a top-level object")
        elif section == "module-provider":
            self._validate_module_provider_structure(payload)
            warnings = self._module_provider_validation_warnings(payload)
        else:
            self._validate_payload(section, payload)
        return content, payload, warnings

    def _validate_module_provider_structure(self, payload: object) -> None:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="module-provider settings must be a top-level object")
        if not isinstance(payload.get("providers"), dict):
            raise HTTPException(status_code=400, detail="moduleProvider.json field 'providers' must be an object")

    def _module_provider_validation_warnings(self, payload: dict) -> list[str]:
        warnings: list[str] = []
        config_loader = ConfigLoader()
        for provider_id, provider in payload["providers"].items():
            if not str(provider_id or "").strip():
                warnings.append("provider id must be non-empty")
                continue
            if not isinstance(provider, dict):
                warnings.append(f"provider '{provider_id}' configuration must be an object")
                continue
            try:
                config_loader._validate_provider_config(str(provider_id), provider, require_api_key=False)
            except ValueError as exc:
                warnings.append(str(exc))
        return warnings

    def _parse_content(self, section: str, content: object) -> dict:
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="content must be a JSON string")
        try:
            payload = json.loads(content)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"{section} settings JSON is invalid: {exc}") from exc
        self._validate_payload(section, payload)
        return payload

    def _validate_payload(self, section: str, payload: object) -> None:
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail=f"{section} settings must be a top-level object")
        if section == "module-provider":
            self._validate_module_provider_structure(payload)
            providers = payload["providers"]
            config_loader = ConfigLoader()
            for provider_id, provider in providers.items():
                if not str(provider_id or "").strip():
                    raise HTTPException(status_code=400, detail="provider id must be non-empty")
                if not isinstance(provider, dict):
                    raise HTTPException(
                        status_code=400,
                        detail=f"provider '{provider_id}' configuration must be an object",
                    )
                try:
                    config_loader._validate_provider_config(str(provider_id), provider, require_api_key=False)
                except ValueError as exc:
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        elif section == "defaults":
            for key in ("server", "agentNode", "graphRunner", "consoleCommand", "nodeMemory", "mcpServers"):
                value = payload.get(key)
                if value is not None and not isinstance(value, dict):
                    raise HTTPException(status_code=400, detail=f"config.json field '{key}' must be an object")
            agent_node = payload.get("agentNode")
            if isinstance(agent_node, dict):
                for bool_key in ("reviewNodeRunsWithCompanion", "reviseToolFailureMemoryWithCompanion"):
                    value = agent_node.get(bool_key)
                    if value is not None and not isinstance(value, bool):
                        raise HTTPException(
                            status_code=400,
                            detail=f"config.json field 'agentNode.{bool_key}' must be a boolean",
                        )
        elif section == "companion":
            type_id = str(payload.get("type_id") or "agent_node").strip() or "agent_node"
            if type_id != "agent_node":
                raise HTTPException(status_code=400, detail="companion config field 'type_id' must be 'agent_node'")
            for key in ("tools", "mcp_servers", "skills", "plugins"):
                value = payload.get(key)
                if value is not None and not isinstance(value, list):
                    raise HTTPException(status_code=400, detail=f"companion config field '{key}' must be a list")
            ui = payload.get("ui")
            if ui is not None and not isinstance(ui, dict):
                raise HTTPException(status_code=400, detail="companion config field 'ui' must be an object")
        elif section == "events":
            runtime_events = getattr(self.core, "runtime_events", None)
            registry = getattr(runtime_events, "registry", None)
            compile_config = getattr(registry, "compile", None)
            if callable(compile_config):
                try:
                    compile_config(payload, strict_sources=True)
                except Exception as exc:
                    errors = getattr(exc, "errors", None)
                    if isinstance(errors, list):
                        detail = "; ".join(
                            str(item.get("message") if isinstance(item, dict) else item)
                            for item in errors[:5]
                        )
                        raise HTTPException(status_code=400, detail=detail or "events config validation failed") from exc
                    raise HTTPException(status_code=400, detail=str(exc)) from exc
        elif section == "theme":
            try:
                validate_theme_config(payload)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc

    def list_settings_sections(self):
        sections = []
        for section_id in SETTINGS_SECTIONS:
            meta = self._section_meta(section_id)
            sections.append(
                {
                    "id": meta["id"],
                    "label": meta["label"],
                    "path": self._settings_path(section_id),
                    "filename": meta["filename"],
                }
            )
        return {"sections": sections}

    def get_settings_section(self, section: str):
        meta = self._section_meta(section)
        path = self._settings_path(meta["id"])
        content, payload, warnings = self._read_payload(path, meta["id"])
        return {
            "section": meta["id"],
            "label": meta["label"],
            "path": path,
            "content": content,
            "data": payload,
            "warnings": warnings,
            **({"active_preset_id": active_theme_preset_id(), **list_theme_presets()} if meta["id"] == "theme" else {}),
        }

    def update_settings_section(self, section: str, payload: dict):
        meta = self._section_meta(section)
        path = self._settings_path(meta["id"])
        parsed = self._parse_content(meta["id"], (payload or {}).get("content"))
        content = json.dumps(parsed, ensure_ascii=False, indent=2) + "\n"
        try:
            atomic_write_text(path, content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to write {meta['id']} settings: {exc}") from exc
        return {
            "ok": True,
            "section": meta["id"],
            "label": meta["label"],
            "path": path,
            "content": content,
            "data": parsed,
            "warnings": [],
            **({"active_preset_id": active_theme_preset_id(), **list_theme_presets()} if meta["id"] == "theme" else {}),
        }

    def get_theme_image(self, asset_path: str, preset: str | None = None):
        return theme_image_response(asset_path, preset=preset)

    def list_theme_presets(self):
        return list_theme_presets()

    def load_theme_preset(self, payload: dict | None = None):
        preset_id = str((payload or {}).get("preset_id") or "").strip()
        try:
            data = load_theme_preset(preset_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except (ValueError, json.JSONDecodeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        content = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
        return {
            "ok": True,
            "section": "theme",
            "label": "Theme",
            "path": theme_config_path(),
            "content": content,
            "data": data,
            **list_theme_presets(),
        }

    def save_theme_preset(self, payload: dict | None = None):
        preset_id = str((payload or {}).get("preset_id") or "").strip()
        content = (payload or {}).get("content")
        if not isinstance(content, str):
            raise HTTPException(status_code=400, detail="content must be a JSON string")
        try:
            data = json.loads(content)
            data = save_theme_preset(preset_id, data)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail=f"theme preset JSON is invalid: {exc}") from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "ok": True,
            "section": "theme",
            "label": "Theme",
            "path": theme_config_path(),
            "content": json.dumps(data, ensure_ascii=False, indent=2) + "\n",
            "data": data,
            **list_theme_presets(),
        }

    def upload_theme_asset(self, file: UploadFile = File(...), preset_id: str = Form("")):
        try:
            return save_theme_asset(file, preset_id=preset_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to save theme image: {exc}") from exc

    def get_provider_limits(self):
        try:
            return read_provider_limit_file()
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to read ProviderLimit.json: {exc}") from exc

    def get_provider_pressure(self):
        try:
            return {"ok": True, **get_provider_pressure_manager().snapshot()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to read provider pressure: {exc}") from exc

    def get_tool_stats(self):
        try:
            return {
                "summary": load_tool_stats_summary(),
                "recent_calls": load_recent_tool_call_stats(),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to read tool stats: {exc}") from exc

    def clear_tool_stats(self):
        try:
            clear_tool_stats_store()
            return {
                "ok": True,
                "summary": load_tool_stats_summary(),
                "recent_calls": load_recent_tool_call_stats(),
            }
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to clear tool stats: {exc}") from exc

    def delete_optional_memory(self):
        script_path = self._delete_operational_memory_script_path()
        if not os.path.isfile(script_path):
            raise HTTPException(status_code=404, detail=f"delete_operational_memory.bat not found: {script_path}")

        workspace_root = workspace_settings.get_workspace_root()
        command = ["cmd.exe", "/c", script_path] if os.name == "nt" else [script_path]
        try:
            completed = subprocess.run(
                command,
                cwd=workspace_root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=120,
            )
        except subprocess.TimeoutExpired as exc:
            raise HTTPException(status_code=500, detail="delete_operational_memory.bat timed out") from exc
        except OSError as exc:
            raise HTTPException(status_code=500, detail=f"failed to run delete_operational_memory.bat: {exc}") from exc

        stdout = str(completed.stdout or "").strip()
        stderr = str(completed.stderr or "").strip()
        if completed.returncode != 0:
            detail = stderr or stdout or f"exit code {completed.returncode}"
            raise HTTPException(status_code=500, detail=f"delete_operational_memory.bat failed: {detail}")

        return {
            "ok": True,
            "returncode": completed.returncode,
            "stdout": stdout,
            "stderr": stderr,
        }

    def start_provider_limit_tests(self, payload: dict | None = None):
        running = self.core.provider_limit_jobs.latest_running()
        if running is not None:
            return {"ok": True, "job": running, "result": self.core.provider_limit_jobs.read_result()}
        timeout_seconds = self._provider_limit_timeout(payload)
        try:
            job = self.core.provider_limit_jobs.start(timeout_seconds=timeout_seconds)
            return {"ok": True, "job": job, "result": self.core.provider_limit_jobs.read_result()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to start provider limit tests: {exc}") from exc

    def start_provider_model_discovery(self, payload: dict | None = None):
        running = self.core.provider_limit_jobs.latest_running()
        if running is not None:
            return {"ok": True, "job": running, "result": self.core.provider_limit_jobs.read_result()}
        timeout_seconds = self._provider_limit_timeout(payload)
        try:
            job = self.core.provider_limit_jobs.start_model_discovery(timeout_seconds=timeout_seconds)
            return {"ok": True, "job": job, "result": self.core.provider_limit_jobs.read_result()}
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to start provider model discovery: {exc}") from exc

    def get_provider_limit_test_job(self, job_id: str):
        job = self.core.provider_limit_jobs.get(job_id)
        if job.get("status") == "not_found":
            raise HTTPException(status_code=404, detail="provider limit test job not found")
        return {"ok": True, "job": job, "result": self.core.provider_limit_jobs.read_result()}

    def _provider_limit_timeout(self, payload: dict | None) -> float:
        raw_timeout = (payload or {}).get("timeout_seconds")
        try:
            timeout_seconds = float(raw_timeout) if raw_timeout not in {None, ""} else 30.0
        except Exception:
            raise HTTPException(status_code=400, detail="timeout_seconds must be a number")
        if timeout_seconds <= 0:
            raise HTTPException(status_code=400, detail="timeout_seconds must be greater than 0")
        return timeout_seconds

__all__ = ["SettingsApiDomain"]
