"""Single worker process owns PDFium. Text and PDF pages are consumed incrementally."""
import json
from pathlib import Path
import uuid
import sys

from .contracts import LibraryConfig
from .database import Database
from .document_types import DocumentError, Passage, TEXT_EXTENSIONS, WORD_EXTENSIONS, TABLE_EXTENSIONS
from .scanner import check_stop, Interrupted
from .text import tokens


def split_text(text: str, size: int, overlap: int, *, page=None, line=None):
    start = 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            boundary = text.rfind("\n", start + size // 2, end)
            if boundary > start:
                end = boundary + 1
        piece = text[start:end]
        if piece.strip():
            yield Passage(piece, page, line)
        if end == len(text):
            break
        next_start = max(start + 1, end - overlap)
        if line is not None:
            line += text[start:next_start].count("\n")
        start = next_start


def passages(path: Path, config: LibraryConfig, stop, warnings: list[str]):
    suffix = path.suffix.lower()
    if suffix in WORD_EXTENSIONS:
        from .word_reader import word_passages
        yield from word_passages(path, config, stop, warnings)
    elif suffix in TABLE_EXTENSIONS:
        from .workbook_reader import spreadsheet_passages
        yield from spreadsheet_passages(path, config, stop, warnings)
    elif suffix == ".pdf" and sys.platform == "android":
        from pypdf import PdfReader
        empty_pages = 0
        with path.open("rb") as stream:
            document = PdfReader(stream, strict=True)
            for index, page in enumerate(document.pages):
                check_stop(stop)
                text = page.extract_text()
                if len(text) > config.max_page_chars:
                    raise DocumentError(f"第 {index + 1} 页超过字符上限，未发布不完整索引")
                if not text.strip():
                    empty_pages += 1
                yield from split_text(text, config.chunk_size, config.chunk_overlap, page=index + 1)
        if empty_pages:
            warnings.append(f"{empty_pages} 页没有可提取文本（空白或扫描页）；首版未执行 OCR")
    elif suffix == ".pdf":
        import pypdfium2 as pdfium
        empty_pages = 0
        with pdfium.PdfDocument(str(path)) as document:
            for index in range(len(document)):
                check_stop(stop)
                page = document[index]
                textpage = page.get_textpage()
                try:
                    if textpage.count_chars() > config.max_page_chars:
                        raise DocumentError(f"第 {index + 1} 页超过字符上限，未发布不完整索引")
                    text = textpage.get_text_bounded(errors="strict")
                finally:
                    textpage.close()
                    page.close()
                if not text.strip():
                    empty_pages += 1
                yield from split_text(text, config.chunk_size, config.chunk_overlap, page=index + 1)
        if empty_pages:
            warnings.append(f"{empty_pages} 页没有可提取文本（空白或扫描页）；首版未执行 OCR")
    elif suffix in TEXT_EXTENSIONS:
        # Fixed-size reads also bound memory for Markdown with extremely long lines.
        with path.open("r", encoding="utf-8-sig", errors="strict", newline=None) as handle:
            buffer, line = "", 1
            while True:
                check_stop(stop)
                part = handle.read(config.chunk_size * 8)
                buffer += part
                if not part:
                    yield from split_text(buffer, config.chunk_size, config.chunk_overlap, line=line)
                    break
                while len(buffer) > config.chunk_size:
                    end = config.chunk_size
                    boundary = buffer.rfind("\n", end // 2, end)
                    if boundary > 0:
                        end = boundary + 1
                    if buffer[:end].strip():
                        yield Passage(buffer[:end], None, line)
                    advance = end - config.chunk_overlap
                    line += buffer[:advance].count("\n")
                    buffer = buffer[advance:]
    else:
        raise DocumentError(f"不支持的文档格式：{suffix}")


def parse_pending(store: Database, config: LibraryConfig, stop, document_limit=100):
    root = Path(config.folder)
    for _ in range(document_limit):
        check_stop(stop)
        with store.connect() as db:
            row = db.execute("SELECT * FROM documents WHERE state IN ('pending','parsing') "
                             "ORDER BY CASE state WHEN 'parsing' THEN 0 ELSE 1 END,id LIMIT 1").fetchone()
        if row is None:
            return
        revision, document_id = uuid.uuid4().hex, row["id"]
        with store.connect() as db:
            db.execute("DELETE FROM chunks WHERE document_id=? AND active=0", (document_id,))
            db.execute("UPDATE documents SET state='parsing',revision=?,error='',warning='' WHERE id=?", (revision, document_id))
            db.execute("UPDATE job SET current_path=? WHERE id=1", (row["path"],))
        path, count, batch, warnings = root / row["path"], 0, [], []
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_relative_to(root):
                raise DocumentError("文件解析路径超出资料目录")
            if row["size"] > config.max_file_mb * 1024 * 1024:
                raise DocumentError(f"文件超过 {config.max_file_mb} MB 上限")
            for passage in passages(resolved, config, stop, warnings):
                check_stop(stop)
                batch.append((document_id, revision, count, passage.page, passage.line, passage.text,
                              tokens(passage.text), json.dumps(passage.location, ensure_ascii=False)))
                count += 1
                if len(batch) >= 128:
                    _insert(store, batch)
                    batch = []
            _insert(store, batch)
            final = path.stat()
            if (final.st_size, final.st_mtime_ns) != (row["size"], row["mtime_ns"]):
                raise DocumentError("解析期间文件发生变化，请重新扫描")
            if not count:
                raise DocumentError("没有可提取文本；扫描 PDF 需要先执行 OCR")
            with store.connect() as db:
                db.execute("UPDATE documents SET state='embedding',chunk_count=?,warning=? WHERE id=?",
                           (count, "; ".join(warnings), document_id))
        except Interrupted:
            raise
        except Exception as exc:
            # Per-document parser failures are persisted, not silently dropped.
            # Storage errors must stop the job, rather than marking arbitrary files bad.
            import sqlite3
            if isinstance(exc, sqlite3.Error):
                raise
            with store.connect() as db:
                db.execute("DELETE FROM chunks WHERE document_id=? AND active=0", (document_id,))
                db.execute("UPDATE documents SET state='error',error=? WHERE id=?", (f"{type(exc).__name__}: {exc}"[:2000], document_id))


def _insert(store, batch):
    if batch:
        with store.connect() as db:
            db.executemany("INSERT INTO chunks(document_id,revision,ordinal,page,line,text,tokens,location) VALUES(?,?,?,?,?,?,?,?)", batch)
