from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class LibraryConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=120)
    folder: str = Field(min_length=1)
    embedding_url: str = Field(min_length=1)
    embedding_model: str = Field(min_length=1, max_length=200)
    dimensions: int = Field(default=1024, ge=8, le=8192)
    api_key_alias: str = ""
    batch_size: int = Field(default=32, ge=1, le=128)
    chunk_size: int = Field(default=1600, ge=256, le=8000)
    chunk_overlap: int = Field(default=200, ge=0, le=1000)
    request_timeout: int = Field(default=60, ge=5, le=300)
    retry_interval_seconds: int = Field(default=5, ge=1, le=300)
    max_file_mb: int = Field(default=256, ge=1, le=4096)
    max_page_chars: int = Field(default=200000, ge=10000, le=2000000)
    spreadsheet_header_row: int = Field(default=0, ge=0, le=1048576)
    allow_agents: bool = True

    @field_validator("name", "embedding_model", "folder")
    @classmethod
    def nonblank(cls, value):
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("embedding_url")
    @classmethod
    def endpoint(cls, value):
        value = value.strip().rstrip("/")
        url = urlsplit(value)
        if url.scheme not in {"http", "https"} or not url.hostname or url.username or url.password or url.query or url.fragment:
            raise ValueError("use an HTTP(S) embeddings endpoint without credentials, query or fragment")
        if url.path.endswith("/embeddings/multimodal"):
            raise ValueError("当前客户端使用 OpenAI 文本 Embedding 协议，尚未实现多模态请求协议")
        return value if url.path.endswith("/embeddings") else value + "/embeddings"

    @field_validator("api_key_alias")
    @classmethod
    def key_alias(cls, value):
        if value is not None and value != value.strip():
            raise ValueError("API Key Name 不能包含首尾空白")
        return value

    @model_validator(mode="after")
    def overlap(self):
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class LibraryUpdate(LibraryConfig):
    # None retains the reference; an empty string selects an unauthenticated service.
    api_key_alias: str | None = None


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    query: str = Field(min_length=1, max_length=2000)
    limit: int = Field(default=10, ge=1, le=30)
    mode: Literal["hybrid", "semantic", "keyword"] = "hybrid"


class Operation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["scan", "resume", "pause", "retry"]


def checked_folder(value: str) -> str:
    path = Path(value).expanduser()
    if not path.is_absolute() or not path.is_dir():
        raise ValueError("资料目录必须是后端机器上存在的绝对路径")
    return str(path.resolve())
