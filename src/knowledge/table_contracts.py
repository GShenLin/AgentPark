"""Declarative spreadsheet queries: no SQL, Python, expressions or file paths."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def column_name(value):
    from openpyxl.utils import column_index_from_string
    if not value.isascii() or not value.isalpha() or not value.isupper():
        raise ValueError("列使用大写 Excel 列字母，例如 A、BC")
    if column_index_from_string(value) > 16384:
        raise ValueError("列不得超过 XFD")
    return value


class TableFilter(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, allow_inf_nan=False)
    column: str
    op: Literal["eq", "ne", "gt", "ge", "lt", "le", "contains", "is_blank", "not_blank"]
    value: str | int | float | bool | None = None

    _column = field_validator("column")(column_name)

    @model_validator(mode="after")
    def operand(self):
        if self.op in {"is_blank", "not_blank"}:
            if self.value is not None:
                raise ValueError("空值过滤不接受 value")
        elif self.value is None:
            raise ValueError("过滤条件需要 value")
        if self.op == "contains" and not isinstance(self.value, str):
            raise ValueError("contains 需要字符串")
        return self


class TableMetric(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    name: str = Field(min_length=1, max_length=80)
    op: Literal["count_rows", "count", "sum", "mean", "min", "max"]
    column: str | None = None

    @field_validator("column")
    @classmethod
    def valid_column(cls, value):
        return None if value is None else column_name(value)

    @model_validator(mode="after")
    def needs_column(self):
        if (self.op == "count_rows") != (self.column is None):
            raise ValueError("count_rows 不接受列；其他统计必须指定列")
        return self


class TableQuery(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    action: Literal["table"]
    library_id: str = Field(min_length=1)
    document_id: int = Field(ge=1)
    sheet: str = Field(min_length=1)
    start_row: int = Field(default=1, ge=1, le=1048576)
    end_row: int | None = Field(default=None, ge=1, le=1048576)
    filters: list[TableFilter] = Field(default_factory=list, max_length=12)
    group_by: list[str] = Field(default_factory=list, max_length=3)
    metrics: list[TableMetric] = Field(min_length=1, max_length=12)

    @field_validator("group_by")
    @classmethod
    def valid_groups(cls, value):
        for name in value:
            column_name(name)
        if len(value) != len(set(value)):
            raise ValueError("分组列重复")
        return value

    @model_validator(mode="after")
    def valid_range(self):
        if self.end_row is not None and self.end_row < self.start_row:
            raise ValueError("end_row 不得小于 start_row")
        names = [metric.name for metric in self.metrics]
        if len(names) != len(set(names)):
            raise ValueError("统计名称不能重复")
        return self
