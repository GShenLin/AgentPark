"""Read registered sources with containment, freshness and bounded output checks."""
from contextlib import contextmanager
from dataclasses import asdict
import json
from pathlib import Path
import threading

from .document_types import DocumentError, TABLE_EXTENSIONS
from .parser import passages
from .workbook_reader import open_workbook


@contextmanager
def checked_source(store, config, document_id):
    with store.connect() as db:
        row = db.execute("SELECT id,path,size,mtime_ns,state,active_revision,revision FROM documents WHERE id=?",
                         (document_id,)).fetchone()
    if row is None:
        raise KeyError("文档不存在，请重新列出或检索知识库")
    root = Path(config.folder).resolve(strict=True)
    path = (root / row["path"]).resolve(strict=True)
    if not path.is_relative_to(root) or not path.is_file():
        raise DocumentError("文档路径超出知识库目录或不是文件")
    before = path.stat()
    if before.st_size > config.max_file_mb * 1024 * 1024:
        raise DocumentError("源文件超过知识库文件大小限制")
    if (before.st_size, before.st_mtime_ns) != (row["size"], row["mtime_ns"]):
        raise DocumentError("源文件已变化，请增量扫描后再读取或计算，避免与索引混用")
    yield path, {"document_id": document_id, "path": row["path"], "document_state": row["state"],
                 "source_mtime_ns": before.st_mtime_ns, "source_size": before.st_size,
                 "index_current": row["state"] == "ready" and row["active_revision"] == row["revision"]}
    after = path.stat()
    if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
        raise DocumentError("读取期间源文件发生变化，结果已丢弃，请重新扫描")


def read_source(store, config, request):
    stop = threading.Event()
    with checked_source(store, config, request.document_id) as (path, metadata):
        if path.suffix.lower() in TABLE_EXTENSIONS:
            with open_workbook(path, config, stop) as book:
                result = {**metadata, **book.metadata()}
                if request.sheet is None:
                    if request.offset:
                        raise DocumentError("请指定 sheet 后按行分页")
                    return result
                rows = []
                output_chars = 0
                iterator = book.rows(request.sheet, request.offset + 1, request.offset + request.limit + 1)
                try:
                    for number, cells in iterator:
                        output_chars += len(json.dumps(cells, ensure_ascii=False))
                        if output_chars > 200000:
                            raise DocumentError("读取结果超过 20 万字符，请减少 limit")
                        rows.append({"row": number, "cells": cells})
                finally:
                    iterator.close()
                result.update(sheet=request.sheet, rows=rows[:request.limit],
                              next_offset=request.offset + request.limit if len(rows) > request.limit else None,
                              offset_unit="row")
        else:
            if request.sheet is not None:
                raise DocumentError("只有 Excel 文档接受 sheet 参数")
            warnings, items = [], []
            iterator = passages(path, config, stop, warnings)
            more = False
            try:
                for ordinal, passage in enumerate(iterator):
                    if ordinal < request.offset:
                        continue
                    if len(items) == request.limit:
                        more = True
                        break
                    items.append({"ordinal": ordinal, **asdict(passage)})
            finally:
                iterator.close()
            result = {**metadata, "passages": items, "warnings": warnings, "offset_unit": "passage",
                      "next_offset": request.offset + request.limit if more else None}
        if len(json.dumps(result, ensure_ascii=False)) > 200000:
            raise DocumentError("读取结果超过 20 万字符，请减少 limit")
        return result
