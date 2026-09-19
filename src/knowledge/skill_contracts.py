"""Internal action contracts shared by knowledge discovery, read and analysis tools."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, model_validator

from .contracts import SearchRequest
from .table_contracts import TableQuery


class ListLibraries(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["list"]
    library_id: str | None = Field(default=None, min_length=1)
    after: int = Field(default=0, ge=0)
    limit: int = Field(default=50, ge=1, le=100)

    @model_validator(mode="after")
    def pagination_target(self):
        if self.library_id is None and (self.after != 0 or self.limit != 50):
            raise ValueError("文档分页需要 library_id")
        return self


class SearchLibrary(SearchRequest):
    action: Literal["search"]
    library_id: str = Field(min_length=1)


class ReadPassage(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["read"]
    library_id: str = Field(min_length=1)
    chunk_id: int | None = Field(default=None, ge=1)
    document_id: int | None = Field(default=None, ge=1)
    sheet: str | None = Field(default=None, min_length=1)
    offset: int = Field(default=0, ge=0, le=1048576)
    limit: int = Field(default=20, ge=1, le=100)

    @model_validator(mode="after")
    def target(self):
        if (self.chunk_id is None) == (self.document_id is None):
            raise ValueError("chunk_id 和 document_id 必须且只能提供一个")
        if self.chunk_id is not None and (self.sheet is not None or self.offset or self.limit != 20):
            raise ValueError("读取索引片段时不接受 sheet、offset 或自定义 limit")
        return self


knowledge_request = TypeAdapter(Annotated[
    ListLibraries | SearchLibrary | ReadPassage | TableQuery, Field(discriminator="action"),
])
