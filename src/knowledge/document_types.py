"""Shared parser records and supported formats (independent of the index)."""
from dataclasses import dataclass, field


TEXT_EXTENSIONS = {".md", ".markdown", ".txt"}
WORD_EXTENSIONS = {".docx", ".doc"}
TABLE_EXTENSIONS = {".xlsx", ".xls"}
EXTENSIONS = TEXT_EXTENSIONS | WORD_EXTENSIONS | TABLE_EXTENSIONS | {".pdf"}


class DocumentError(ValueError):
    pass


@dataclass
class Passage:
    text: str
    page: int | None = None
    line: int | None = None
    location: dict = field(default_factory=dict)
