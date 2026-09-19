"""Bound compressed Office inputs before readers allocate their in-memory parts."""
from zipfile import ZipFile

from .document_types import DocumentError


def check_office_zip(path, max_file_mb):
    with ZipFile(path) as archive:
        entries = archive.infolist()
        if len(entries) > 100000:
            raise DocumentError("Office 压缩包文件数超过 100000 上限")
        # Resource bound also covers sharedStrings, styles and Word XML trees.
        budget = min(max_file_mb, 256) * 1024 * 1024
        if sum(item.file_size for item in entries) > budget:
            raise DocumentError(f"Office 解压后大小超过 {budget // 1024 // 1024} MB 上限")
