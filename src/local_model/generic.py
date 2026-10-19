from pathlib import Path

from .http import LocalHttp
from .service_adapter import LaunchSpec, ServiceAdapter


class GenericAdapter(ServiceAdapter):
    def launch_issues(self) -> list[str]:
        issues = []
        if not self.config["executable"]:
            issues.append("仅登记服务地址；配置启动程序和工作目录后可在此启动")
        elif not Path(self.config["executable"]).is_file():
            issues.append("启动程序不存在")
        elif Path(self.config["executable"]).suffix.lower() in {".bat", ".cmd", ".ps1", ".sh", ".py"}:
            issues.append("启动程序请填写解释器或可执行文件，脚本路径作为启动参数传入")
        if not self.config["install_path"] or not Path(self.config["install_path"]).is_dir():
            issues.append("工作目录不存在或未配置")
        return issues

    def inspect(self) -> dict:
        online, error = self.probe_ready()
        return {"installed": not self.launch_issues(), "online": online, "loaded": None,
                "active_model": None, "models": [], "issues": [], "connection_error": error, "detail": None}

    def probe_ready(self) -> tuple[bool | None, str]:
        if not self.config["health_path"]:
            return None, ""
        return LocalHttp(self.config["endpoint"]).probe_status(self.config["health_path"])

    def launch(self, model_id: str) -> LaunchSpec:
        issues = self.launch_issues()
        if issues:
            raise ValueError("；".join(issues))
        return LaunchSpec([self.config["executable"], *self.config["extra_args"]], self.config["install_path"])

    def prepare_stop(self) -> None:
        # No model or queue protocol is assumed for a custom service.
        return None
