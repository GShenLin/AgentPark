import json
import os
import shutil
import uuid
from pathlib import Path

import yaml

from .http import LocalHttp
from .service_adapter import ModelServiceAdapter


CATEGORIES = ("checkpoints", "diffusion_models", "unet", "text_encoders", "clip", "vae", "loras",
              "controlnet", "upscale_models", "embeddings", "clip_vision", "audio_encoders")
EXTENSIONS = {".safetensors", ".gguf", ".ckpt", ".pt", ".pth", ".bin"}


class ComfyAdapter(ModelServiceAdapter):
    def __init__(self, config: dict):
        self.config = config
        self.root = Path(config["install_path"])
        self.http = LocalHttp(config["endpoint"])

    def folders(self):
        result = [(name, self.root / "models" / name) for name in CATEGORIES]
        path = self.root / "extra_model_paths.yaml"
        if path.exists():
            document = yaml.safe_load(path.read_text(encoding="utf-8-sig"))
            if not isinstance(document, dict):
                raise ValueError("extra_model_paths.yaml 必须是对象")
            for entry in document.values():
                if not isinstance(entry, dict):
                    raise ValueError("extra_model_paths.yaml 路径组必须是对象")
                base = Path(os.path.expandvars(os.path.expanduser(str(entry.get("base_path", self.root)))))
                if not base.is_absolute():
                    base = self.root / base
                for name, value in entry.items():
                    if name in {"base_path", "is_default"}:
                        continue
                    if not isinstance(value, str):
                        raise ValueError(f"extra_model_paths.yaml: {name} 必须是路径字符串")
                    for part in value.splitlines():
                        if part.strip():
                            result.append((name, base / os.path.expandvars(os.path.expanduser(part.strip()))))
        return result

    def inspect(self):
        models, issues, seen = [], [], set()
        for category, folder in self.folders():
            if not folder.exists():
                continue
            for path in sorted(folder.rglob("*")):
                if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                    continue
                identity = (category, str(path.resolve()))
                if identity in seen:
                    continue
                seen.add(identity)
                models.append({"id": str(path), "name": str(path.relative_to(folder)), "category": category,
                               "path": str(path), "available": True, "missing": [], "bytes": path.stat().st_size})
        health, error = self.http.probe("/system_stats")
        online = (isinstance(health, dict) and isinstance(health.get("system"), dict)
                  and "comfyui_version" in health["system"])
        if health is not None and not online:
            error = "该地址响应的不是可识别的 ComfyUI 服务"
        if online:
            # The running server includes custom-node and command-line model paths.
            categories = self.http.request("/models")
            if not isinstance(categories, list) or not all(isinstance(x, str) for x in categories):
                raise ValueError("ComfyUI /models 响应格式不正确")
            from urllib.parse import quote
            for category in categories:
                if category not in CATEGORIES:
                    continue
                names = self.http.request("/models/" + quote(category, safe=""))
                if not isinstance(names, list) or not all(isinstance(x, str) for x in names):
                    raise ValueError("ComfyUI 模型列表响应格式不正确")
                known = {(m["category"], m["name"]) for m in models}
                for name in names:
                    if (category, name) not in known:
                        models.append({"id": category + "/" + name, "name": name, "category": category,
                                       "path": "服务报告的模型（外部目录）", "available": True,
                                       "missing": [], "bytes": None})
        return {"installed": (self.root / "main.py").is_file() and (self.root / "folder_paths.py").is_file(),
                "online": online, "loaded": None, "active_model": None, "models": models,
                "issues": issues, "connection_error": error, "detail": health if online else None}

    def command(self, python: str, model_id: str, port: int):
        return [python, str(self.root / "main.py"), "--listen", "127.0.0.1", "--port", str(port)]

    def probe_ready(self) -> tuple[bool, str]:
        health, error = self.http.probe("/system_stats")
        ready = (isinstance(health, dict) and isinstance(health.get("system"), dict)
                 and "comfyui_version" in health["system"])
        return ready, error or ("" if ready else "该地址响应的不是可识别的 ComfyUI 服务")

    def prepare_stop(self) -> None:
        health, _ = self.http.probe("/system_stats")
        if health is not None:
            self.idle()

    def idle(self):
        health = self.http.request("/system_stats")
        if "comfyui_version" not in health.get("system", {}):
            raise RuntimeError("服务身份不匹配")
        queue = self.http.request("/queue")
        if "queue_running" not in queue or "queue_pending" not in queue:
            raise ValueError("ComfyUI 队列响应格式不正确")
        if queue["queue_running"] or queue["queue_pending"]:
            raise RuntimeError("ComfyUI 仍有运行中或排队的任务，请完成后再操作")

    def unload(self):
        self.idle()
        self.http.request("/free", {"unload_models": True, "free_memory": True})
        return {"message": "已提交模型释放请求。ComfyUI 异步处理；接口未提供逐模型卸载完成状态。"}

    def load(self, model_id: str):
        path = Path(self.config["workflow_path"])
        if not self.config["workflow_path"] or not path.is_file():
            raise ValueError("请先配置导出为 API 格式的工作流 JSON 文件")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not data or not all(
                isinstance(v, dict) and isinstance(v.get("class_type"), str) and isinstance(v.get("inputs"), dict)
                for v in data.values()):
            raise ValueError("请选择 ComfyUI 导出的 API 格式工作流，不是包含 nodes/links 的编辑器文件")
        self.idle()
        result = self.http.request("/prompt", {"prompt": data}, timeout=30)
        if not result.get("prompt_id") or result.get("node_errors"):
            raise RuntimeError(f"工作流提交失败：{result}")
        return {"message": "工作流已进入队列，将按流程加载模型并生成结果；可在 ComfyUI 查看进度。",
                "prompt_id": result["prompt_id"]}

    def import_model(self, source: str, category: str):
        path = Path(source)
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() not in EXTENSIONS:
            raise ValueError("请选择本机已有模型文件的绝对路径")
        if category not in CATEGORIES:
            raise ValueError("请选择支持的模型目录类型")
        folder = self.root / "models" / category
        folder.mkdir(parents=True, exist_ok=True)
        target = folder / path.name
        if path.resolve() == target.resolve():
            return {"message": "文件已在模型目录中，可直接扫描"}
        if target.exists():
            raise ValueError("同名模型已经存在，不会覆盖")
        if shutil.disk_usage(folder).free < path.stat().st_size:
            raise ValueError("目标磁盘空间不足")
        temporary = folder / (".import-" + uuid.uuid4().hex)
        try:
            shutil.copyfile(path, temporary)
            # Exclusive destination creation prevents a competing import overwriting a model.
            os.link(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return {"message": "模型已复制到所选目录；具体兼容性由工作流的模型加载节点验证"}
