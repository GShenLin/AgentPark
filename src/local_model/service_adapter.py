"""Service lifecycle boundary, independent of optional model management."""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

from .contracts import Action


@dataclass(frozen=True)
class LaunchSpec:
    command: list[str]
    cwd: str


class ServiceAdapter(ABC):
    actions: tuple[Action, ...] = ("start", "stop")

    def __init__(self, config: dict):
        self.config = config

    @abstractmethod
    def inspect(self) -> dict: ...

    @abstractmethod
    def launch(self, model_id: str) -> LaunchSpec: ...

    @abstractmethod
    def probe_ready(self) -> tuple[bool | None, str]: ...

    @abstractmethod
    def prepare_stop(self) -> None: ...

    @abstractmethod
    def launch_issues(self) -> list[str]: ...


class ModelServiceAdapter(ServiceAdapter):
    actions: tuple[Action, ...] = ("start", "stop", "load", "unload", "import")

    def python(self) -> str:
        return self.config["python_path"] or str(Path(self.config["install_path"]) / ".venv" /
                                               ("Scripts/python.exe" if os.name == "nt" else "bin/python"))

    def launch_issues(self) -> list[str]:
        return [] if Path(self.python()).is_file() else ["未找到 Python 环境，请配置实际使用的 Python 可执行文件"]

    def launch(self, model_id: str) -> LaunchSpec:
        from urllib.parse import urlsplit

        issues = self.launch_issues()
        if issues:
            raise ValueError("；".join(issues))
        address = urlsplit(self.config["endpoint"])
        command = self.command(self.python(), model_id, address.port)
        if address.hostname == "::1":
            command = ["::1" if part == "127.0.0.1" else part for part in command]
        return LaunchSpec(command + self.config["extra_args"], self.config["install_path"])

    @abstractmethod
    def command(self, python: str, model_id: str, port: int) -> list[str]: ...

    @abstractmethod
    def load(self, model_id: str) -> dict: ...

    @abstractmethod
    def unload(self) -> dict: ...

    @abstractmethod
    def import_model(self, source: str, category: str) -> dict: ...
