"""Conversation projection and conflict-aware merge across active and Archive."""
from __future__ import annotations

import copy
import json
import uuid
from pathlib import Path
from urllib.parse import unquote, urlparse
from src.file_transaction import run_with_interprocess_lock

from .blobs import BlobStore, digest, encode, file_digest, read_json, write_json
from .contracts import Entry, Node, Record, SyncConflict
from .journal import commit
from ..node_memory_paths import iter_archive_date_dirs
from ..node_memory_markdown import render_memory_markdown_entry

ROLES = {"user", "human", "assistant", "agent"}


def files(directory: Path) -> dict[str, list[dict]]:
    paths = [Path(p) / "messages.jsonl" for p in iter_archive_date_dirs(str(directory), reverse=False)]
    paths.append(directory / "messages.jsonl")
    result = {}
    for path in paths:
        records = []
        if path.exists():
            with path.open(encoding="utf-8") as stream:
                for line in stream:
                    if not line.strip():
                        continue
                    record = json.loads(line)
                    if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
                        raise SyncConflict("历史消息缺少稳定 ID，不能进行增量同步。")
                    records.append(record)
        result[path.relative_to(directory).as_posix()] = records
    return result


def identity(directory: Path) -> str:
    path = directory / ".sync-origin.json"
    def load_or_create():
        value = read_json(path)
        if value is None:
            value = {"id": uuid.uuid4().hex}
            write_json(path, value)
        if not isinstance(value, dict) or not isinstance(value.get("id"), str) or not value["id"]:
            raise SyncConflict("同步来源身份文件损坏。")
        return value["id"]
    return run_with_interprocess_lock(str(directory / ".sync-origin.lock"), load_or_create)


def portable(record: dict, blobs: BlobStore | None = None) -> tuple[dict, dict[str, int]]:
    value = copy.deepcopy(record)
    resources = {}
    for part in value["parts"]:
        if part.get("type") == "text":
            continue
        if part.get("type") != "resource" or not isinstance(part.get("resource"), dict):
            raise SyncConflict("不支持的消息内容类型，不能静默丢弃。")
        resource = part["resource"]
        uri = resource["uri"]
        if uri.startswith(("https://", "http://", "data:")):
            continue
        if uri.startswith("file:"):
            parsed = urlparse(uri)
            if parsed.netloc:
                raise SyncConflict("附件使用网络文件路径，请先保存为本地附件。")
            uri = unquote(parsed.path)
            if len(uri) > 2 and uri[0] == "/" and uri[2] == ":":
                uri = uri[1:]
        path = Path(uri)
        if not path.is_absolute() or not path.is_file():
            raise SyncConflict(f"消息附件不存在或不是绝对路径：{uri}")
        sha, size = blobs.put_file(path) if blobs else (file_digest(path), path.stat().st_size)
        resource["uri"] = "sync-blob:" + sha
        resources[sha] = size
    return value, resources


def materialize(record: dict, blobs: BlobStore, attachment_dir: Path) -> dict:
    value = copy.deepcopy(record)
    for part in value["parts"]:
        if part.get("type") != "resource":
            continue
        resource = part["resource"]
        uri = resource["uri"]
        if uri.startswith("sync-blob:"):
            sha = uri.removeprefix("sync-blob:")
            source = blobs.path(sha)
            if not source.is_file() or file_digest(source) != sha:
                raise SyncConflict(f"附件缺失或校验失败：{sha}")
            # Original filenames remain display metadata; never use them as paths.
            suffix = Path(resource.get("name", "")).suffix.lower()
            if not suffix.isascii() or len(suffix) > 12 or not suffix[1:].isalnum():
                suffix = ""
            target = attachment_dir / (sha + suffix)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not target.exists() or file_digest(target) != sha:
                import shutil
                from src.file_transaction import replace_path
                temporary = target.with_name(target.name + "." + uuid.uuid4().hex + ".tmp")
                shutil.copyfile(source, temporary)
                replace_path(str(temporary), str(target))
            resource["uri"] = str(target)
        elif not uri.startswith(("http://", "https://", "data:")):
            raise SyncConflict("同步消息含未声明的本地附件。")
    return value


def export_node(directory: Path, node_id: str, blobs: BlobStore):
    origin = identity(directory)
    ledger = read_json(directory / ".sync-index.json", {})
    by_id = {item["id"]: key for key, item in ledger.items()}
    entries, assets, warnings = [], {}, []
    turn = None
    ids = set()
    for relative, records in files(directory).items():
        for record in records:
            if record["id"] in ids:
                raise SyncConflict(f"{node_id} 存在重复消息 ID，请先修复记忆。")
            ids.add(record["id"])
            key = by_id.get(record["id"], origin + ":" + record["id"])
            if record["role"] in {"user", "human"}:
                turn = key
            if record["role"] == "system":
                warnings.append(f"{node_id}：系统状态/错误未作为最终回答同步（{record['id']}）。")
            if record["role"] not in ROLES:
                continue
            if turn is None:
                warnings.append(f"{node_id}：跳过没有用户轮次的孤立回答 {record['id']}。")
                continue
            value, resources = portable(record, blobs)
            parsed = Record.model_validate(value)
            value = parsed.model_dump(exclude_none=True)
            entry_turn = ledger.get(key, {}).get("turn", turn)
            entries.append(Entry(origin=key, turn=entry_turn, record=parsed,
                                 digest=digest(value), archive=relative.startswith("archive/")))
            assets.update(resources)
    return Node(id=node_id, entries=entries), assets, warnings


def merge(directory: Path, node: Node, blobs: BlobStore, attachment_dir: Path, *, apply=False):
    data = files(directory)
    ledger = read_json(directory / ".sync-index.json", {})
    original_ledger = copy.deepcopy(ledger)
    lookup = {}
    for relative, records in data.items():
        for record in records:
            if record["id"] in lookup:
                raise SyncConflict("目标记忆包含重复消息 ID。")
            lookup[record["id"]] = (relative, record)
    counts = {"added": 0, "updated": 0, "unchanged": 0}
    conflicts, changed = [], set()
    turns: dict[str, list[Entry]] = {}
    for entry in node.entries:
        if digest(entry.record.model_dump(exclude_none=True)) != entry.digest:
            raise SyncConflict("消息内容校验失败。")
        turns.setdefault(entry.turn, []).append(entry)
    for turn_id, entries in turns.items():
        users = [e for e in entries if e.record.role in {"user", "human"}]
        if len(users) != 1 or entries[0] != users[0]:
            raise SyncConflict("同步轮次必须以唯一的用户消息开始。")
        user_id = users[0].record.id
        relative = lookup[user_id][0] if user_id in lookup else (
            f"archive/{users[0].record.created_at[:10]}/messages.jsonl"
            if any(e.archive for e in entries) else "messages.jsonl")
        from datetime import date
        date.fromisoformat(users[0].record.created_at[:10])
        records = data.setdefault(relative, [])
        for entry in entries:
            old = ledger.get(entry.origin)
            record_id = entry.record.id
            existing = lookup.get(record_id)
            if old and old["id"] != record_id:
                raise SyncConflict("同步来源与消息 ID 不匹配。")
            if existing:
                current_file, current = existing
                portable_current, _ = portable(current)
                current_hash = digest(portable_current)
                if current_hash == entry.digest:
                    counts["unchanged"] += 1
                elif old and current_hash == old["applied"]:
                    next_record = materialize(entry.record.model_dump(exclude_none=True), blobs, attachment_dir)
                    target_records = data[current_file]
                    target_records[target_records.index(current)] = next_record
                    lookup[record_id] = (current_file, next_record)
                    counts["updated"] += 1
                    changed.add(current_file)
                else:
                    conflicts.append(f"{node.id} / {record_id}：目标记录已修改或 ID 冲突。")
                    continue
            else:
                if old:
                    conflicts.append(f"{node.id} / {record_id}：目标已删除此记录，不自动恢复。")
                    continue
                value = materialize(entry.record.model_dump(exclude_none=True), blobs, attachment_dir)
                # Append to the matching complete turn, never timestamp-interleave conversations.
                if record_id != user_id and user_id in lookup:
                    relative = lookup[user_id][0]
                    records = data[relative]
                    start = next(i for i, r in enumerate(records) if r["id"] == user_id)
                    end = next((i for i in range(start + 1, len(records))
                                if records[i]["role"] in {"user", "human"}), len(records))
                    records.insert(end, value)
                else:
                    records.append(value)
                lookup[record_id] = (relative, value)
                counts["added"] += 1
                changed.add(relative)
            ledger[entry.origin] = {"id": record_id, "applied": entry.digest, "turn": turn_id}
    if conflicts:
        return {**counts, "conflicts": conflicts}
    if apply and (changed or ledger != original_ledger):
        changes = {".sync-index.json": encode(ledger)}
        for relative in changed:
            records = data[relative]
            changes[relative] = "".join(encode(r) + "\n" for r in records)
            md = str(Path(relative).with_name("memory.md")).replace("\\", "/")
            changes[md] = "".join(render_memory_markdown_entry(r) for r in records)
        commit(directory, changes)
    return {**counts, "conflicts": []}
