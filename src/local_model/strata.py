import json
from pathlib import Path

from .http import LocalHttp


class StrataAdapter:
    def __init__(self, config: dict):
        self.config = config
        self.root = Path(config["install_path"])

    def configs(self):
        return sorted(self.root.glob("strata*.json"))

    def model(self, path: Path) -> dict:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict) or not isinstance(data.get("args"), list) or not data.get("exe"):
            raise ValueError(f"{path.name} 不是 Strata 运行配置")
        if not all(isinstance(x, str) for x in data["args"]):
            raise ValueError(f"{path.name} 的 args 必须是字符串数组")
        cwd = Path(data.get("cwd") or self.root)
        def resolve(value):
            p = Path(value)
            return p if p.is_absolute() else cwd / p
        required = [resolve(data["exe"])]
        for flag in ("--pack", "--native", "--ple-gguf"):
            if flag in data["args"]:
                index = data["args"].index(flag) + 1
                if index == len(data["args"]):
                    raise ValueError(f"{path.name}: {flag} 缺少路径")
                required.append(resolve(data["args"][index]))
        missing = [str(p) for p in required if not p.exists()]
        return {"id": path.name, "name": data.get("model_name", path.stem), "category": "运行配置",
                "path": str(path), "available": not missing, "missing": missing, "bytes": None}

    def selected(self, model_id: str) -> Path:
        for path in self.configs():
            if path.name == model_id:
                model = self.model(path)
                if not model["available"]:
                    raise ValueError("模型配置缺少文件：" + ", ".join(model["missing"]))
                return path
        raise ValueError("请先选择已检测到的 Strata 运行配置")

    def http(self, config_path: Path | None = None):
        keys = set()
        for path in ([config_path] if config_path else self.configs()):
            data = json.loads(path.read_text(encoding="utf-8-sig"))
            if data.get("api_key"):
                keys.add(data["api_key"])
        if len(keys) > 1:
            raise ValueError("多个 Strata 配置使用不同 API key，请分开登记安装目录")
        return LocalHttp(self.config["endpoint"], next(iter(keys), ""))

    def inspect(self):
        models, issues = [], []
        for path in self.configs():
            try:
                models.append(self.model(path))
            except (ValueError, OSError) as exc:
                issues.append(str(exc))
        installed = (self.root / "serve" / "server.py").is_file()
        health, error = self.http().probe("/health")
        online = isinstance(health, dict) and health.get("service") == "strata"
        if health is not None and not online:
            error = "该地址响应的不是可识别的 Strata 服务"
        return {"installed": installed, "online": online,
                "loaded": health.get("loaded") if online else None,
                "active_model": health.get("model") if online else None,
                "models": models, "issues": issues, "connection_error": error,
                "detail": health if online else None}

    def command(self, python: str, model_id: str, port: int):
        path = self.selected(model_id)
        return [python, str(self.root / "serve" / "server.py"), "--engine", "strata", "--config", str(path),
                "--host", "127.0.0.1", "--port", str(port), "--lazy"]

    def load(self, model_id: str):
        path = self.selected(model_id)
        model = self.model(path)
        http = self.http(path)
        health = http.request("/health")
        if health.get("service") != "strata" or health.get("model") != model["name"]:
            raise RuntimeError("当前服务使用另一份模型配置。请先停止服务，再选择目标配置启动。")
        result = http.request("/v1/load", {"model": model["name"]}, timeout=600)
        if result.get("loaded") is not True:
            raise RuntimeError(f"Strata 尚未确认模型加载完成：{result}")
        return {"message": "模型已加载", "detail": result}

    def unload(self):
        http = self.http()
        health = http.request("/health")
        if health.get("service") != "strata":
            raise RuntimeError("服务身份不匹配")
        result = http.request("/v1/unload", {}, timeout=90)
        if result.get("loaded") is not False:
            raise RuntimeError(f"Strata 尚未确认模型卸载完成：{result}")
        return {"message": "模型已卸载，服务保持在线", "detail": result}

    def import_model(self, source: str, category: str):
        path = Path(source)
        if not path.is_absolute() or not path.is_file() or path.suffix.lower() != ".json":
            raise ValueError("请选择已有 Strata 模型运行配置的绝对路径（JSON）")
        self.model(path)
        name = path.name if path.name.startswith("strata") else "strata-" + path.name
        target = self.root / name
        if target.resolve() == path.resolve():
            return {"message": "配置已在安装目录中，可直接扫描"}
        if target.exists():
            raise ValueError("同名配置已经存在，不会覆盖")
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not data.get("cwd"):
            data["cwd"] = str(path.parent)
        with target.open("x", encoding="utf-8") as output:
            json.dump(data, output, ensure_ascii=False, indent=2)
        return {"message": "已登记模型运行配置，权重文件保留在原位置"}
