from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


Action = Literal["start", "stop", "load", "unload", "import"]


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["strata", "comfyui"] | None = None
    install_path: str = ""
    python_path: str = ""
    endpoint: str = ""
    workflow_path: str = ""
    executable: str = ""
    health_path: str = ""
    startup_timeout: int = Field(default=60, ge=1, le=600)
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("extra_args")
    @classmethod
    def startup_args(cls, values: list[str]) -> list[str]:
        if any(not value or "\x00" in value or "\r" in value or "\n" in value for value in values):
            raise ValueError("启动参数必须是一行一个的非空字符串")
        return values

    @field_validator("install_path", "python_path", "workflow_path", "executable")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        value = value.strip()
        if value and not Path(value).is_absolute():
            raise ValueError("请填写服务所在电脑上的绝对路径")
        return value

    @field_validator("endpoint")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        value = value.strip().rstrip("/")
        if not value:
            return value
        parsed = urlsplit(value)
        if (parsed.scheme not in {"http", "https"} or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("请填写本机 HTTP/HTTPS 服务根地址，例如 http://127.0.0.1:8080")
        # Accessing port also validates malformed and out-of-range port values.
        if parsed.port == 0:
            raise ValueError("服务地址不能使用端口 0")
        return value

    @field_validator("health_path")
    @classmethod
    def health_route(cls, value: str) -> str:
        value = value.strip()
        parsed = urlsplit(value)
        if value and (not value.startswith("/") or value.startswith("//") or parsed.fragment
                      or "\\" in value or any(ord(c) < 32 for c in value)):
            raise ValueError("就绪检测路径必须以 / 开头，例如 /health")
        return value

    @model_validator(mode="after")
    def configuration(self):
        if self.kind is not None:
            endpoint = urlsplit(self.endpoint)
            if not self.install_path or endpoint.scheme != "http" or endpoint.port is None:
                raise ValueError("管理预设需要安装目录和带端口的本机 HTTP 根地址")
            if self.executable or self.health_path:
                raise ValueError("管理预设提供启动程序和就绪检测，请勿同时配置自定义入口")
            reserved = {"--port", "--host", "--listen", "--config", "--engine", "--lazy"}
            if any(value.split("=", 1)[0] in reserved for value in self.extra_args):
                raise ValueError("附加参数不能覆盖预设的服务地址、运行配置或延迟加载选项")
        else:
            if self.python_path or self.workflow_path:
                raise ValueError("普通服务请通过启动程序和参数配置，不使用预设专用字段")
            if self.executable and not self.install_path:
                raise ValueError("配置启动程序时必须填写工作目录")
            if not self.executable and self.extra_args:
                raise ValueError("配置启动参数时必须填写启动程序")
            if not self.executable and not self.endpoint:
                raise ValueError("请填写启动程序或已有服务的地址")
            if self.health_path and not self.endpoint:
                raise ValueError("就绪检测需要服务地址")
        return self


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    model_id: str = ""
    source_path: str = ""
    category: str = ""
