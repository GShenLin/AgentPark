from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ServiceConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=100)
    kind: Literal["strata", "comfyui"]
    install_path: str
    python_path: str = ""
    endpoint: str
    workflow_path: str = ""
    extra_args: list[str] = Field(default_factory=list)

    @field_validator("extra_args")
    @classmethod
    def startup_args(cls, values: list[str]) -> list[str]:
        reserved = {"--port", "--host", "--listen", "--config", "--engine", "--lazy"}
        if any(not value or "\x00" in value or value.split("=", 1)[0] in reserved for value in values):
            raise ValueError("附加参数不能覆盖服务地址、运行配置或延迟加载选项")
        return values

    @field_validator("install_path", "python_path", "workflow_path")
    @classmethod
    def absolute_path(cls, value: str) -> str:
        value = value.strip()
        if value and not Path(value).is_absolute():
            raise ValueError("请填写服务所在电脑上的绝对路径")
        return value

    @field_validator("install_path")
    @classmethod
    def required_path(cls, value: str) -> str:
        if not value:
            raise ValueError("安装路径不能为空")
        return value

    @field_validator("endpoint")
    @classmethod
    def local_endpoint(cls, value: str) -> str:
        parsed = urlsplit(value.strip())
        if (parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
                or parsed.username or parsed.password or parsed.query or parsed.fragment
                or parsed.path not in {"", "/"}):
            raise ValueError("请填写本机 HTTP 服务根地址，例如 http://127.0.0.1:8080")
        if parsed.port is None:
            raise ValueError("服务地址必须包含端口")
        return value.strip().rstrip("/")


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["start", "stop", "load", "unload", "import"]
    model_id: str = ""
    source_path: str = ""
    category: str = ""
