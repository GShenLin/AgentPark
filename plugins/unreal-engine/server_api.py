from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import struct
import tempfile
import uuid
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone

from fastapi import HTTPException, Request


CR1_MARKER = b"CR1"
ANSI_FIELD_WIDTH = 260
HEADER_SIZE = len(CR1_MARKER) + (4 + ANSI_FIELD_WIDTH) * 2 + 4 + 4
MAX_FILE_COUNT = 4096
MAX_FILE_SIZE = 512 * 1024 * 1024
MAX_COMPRESSED_PAYLOAD_SIZE = 512 * 1024 * 1024
MAX_UNCOMPRESSED_SIZE = 1024 * 1024 * 1024
CRASH_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,159}$")
PROFILE_ID_PATTERN = re.compile(r"^[A-Za-z0-9_-]+$")


class UeCrashArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class UeCrashArchiveHeader:
    directory_name: str
    file_name: str
    uncompressed_size: int
    file_count: int


@dataclass(frozen=True)
class UeCrashArchiveFile:
    index: int
    name: str
    data: bytes


@dataclass(frozen=True)
class UeCrashArchive:
    header: UeCrashArchiveHeader
    files: tuple[UeCrashArchiveFile, ...]


class UeCrashReceiver:
    def __init__(self, runtime_root: str, core: object) -> None:
        self.runtime_root = os.path.abspath(runtime_root)
        self.core = core

    async def receive_crash(self, request: Request, profile_id: str = ""):
        content_type = str(request.headers.get("content-type") or "").split(";", 1)[0].strip().lower()
        if content_type != "application/octet-stream":
            raise HTTPException(status_code=415, detail="UE crash upload requires application/octet-stream")
        upload_type = str(request.query_params.get("UploadType") or "").strip()
        if upload_type != "crashreports":
            raise HTTPException(status_code=400, detail="UploadType must be crashreports")

        content_length = self._content_length(request)
        if content_length is not None and content_length > MAX_COMPRESSED_PAYLOAD_SIZE:
            raise HTTPException(status_code=413, detail="UE crash payload exceeds the compressed size limit")
        payload_buffer = bytearray()
        async for chunk in request.stream():
            if len(payload_buffer) + len(chunk) > MAX_COMPRESSED_PAYLOAD_SIZE:
                raise HTTPException(status_code=413, detail="UE crash payload exceeds the compressed size limit")
            payload_buffer.extend(chunk)
        payload = bytes(payload_buffer)
        if not payload:
            raise HTTPException(status_code=400, detail="UE crash payload is empty")

        try:
            archive = parse_ue_crash_archive(payload)
        except UeCrashArchiveError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        crash_id = self._crash_id(archive.header.directory_name)
        raw_name = self._archive_filename(archive.header.file_name, crash_id)
        profile_id = self._profile_id(profile_id or request.query_params.get("ProfileID"))
        graph_id = self._graph_id(request.query_params.get("GraphID"))
        self._require_agent_profile(profile_id)
        node_id = self._node_id(crash_id)
        node_name = f"UE Crash {crash_id}"

        created = self.core.profile_api.create_agent_node_from_profile(
            profile_id,
            {
                "graph_id": graph_id,
                "node_id": node_id,
                "name": node_name,
            },
        )
        config_path = str(created.get("config_path") or "").strip()
        if not config_path:
            raise HTTPException(status_code=500, detail="created UE crash agent has no config path")
        node_dir = os.path.dirname(os.path.abspath(config_path))
        final_dir = os.path.join(node_dir, "ue-crash")
        if os.path.exists(final_dir):
            self._rollback_created_node(graph_id, node_id, node_dir)
            raise HTTPException(status_code=409, detail=f"UE crash upload already exists: {crash_id}")

        temp_dir = tempfile.mkdtemp(prefix=".ue-crash.", dir=node_dir)
        try:
            files_dir = os.path.join(temp_dir, "files")
            os.makedirs(files_dir, exist_ok=False)
            for item in archive.files:
                with open(os.path.join(files_dir, item.name), "xb") as handle:
                    handle.write(item.data)
            with open(os.path.join(temp_dir, raw_name), "xb") as handle:
                handle.write(payload)
            metadata = {
                "schema_version": 1,
                "received_at": datetime.now(timezone.utc).isoformat(),
                "crash_id": crash_id,
                "profile_id": profile_id,
                "graph_id": graph_id,
                "node_id": node_id,
                "node_path": node_dir,
                "crash_path": final_dir,
                "directory_name": archive.header.directory_name,
                "archive_file_name": raw_name,
                "compressed_size": len(payload),
                "uncompressed_size": archive.header.uncompressed_size,
                "file_count": archive.header.file_count,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "query": {key: value for key, value in request.query_params.multi_items()},
                "files": [
                    {"index": item.index, "name": item.name, "size": len(item.data)}
                    for item in archive.files
                ],
            }
            with open(os.path.join(temp_dir, "manifest.json"), "x", encoding="utf-8", newline="\n") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.replace(temp_dir, final_dir)
        except FileExistsError as exc:
            self._rollback_created_node(graph_id, node_id, node_dir)
            raise HTTPException(status_code=400, detail=f"UE crash archive contains conflicting files: {exc}") from exc
        except OSError as exc:
            self._rollback_created_node(graph_id, node_id, node_dir)
            raise HTTPException(status_code=500, detail=f"failed to persist UE crash upload: {exc}") from exc
        finally:
            if os.path.isdir(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

        trace_id = uuid.uuid4().hex
        message = {
            "role": "user",
            "parts": [
                {
                    "type": "text",
                    "text": (
                        "A new Unreal Engine crash report was received.\n"
                        f"Crash ID: {crash_id}\n"
                        f"Crash data path: {final_dir}\n"
                        "Inspect manifest.json, the raw .uecrash archive, and files/ in that directory. "
                        "Analyze the crash from those local files."
                    ),
                },
                {
                    "type": "structured",
                    "data": {
                        "event": "ue_crash_received",
                        "crash_id": crash_id,
                        "profile_id": profile_id,
                        "graph_id": graph_id,
                        "node_id": node_id,
                        "node_path": node_dir,
                        "crash_path": final_dir,
                    },
                },
            ],
        }
        try:
            queued = self.core.node_ops.enqueue_node_instance_pending(
                node_id,
                {
                    "payload": message,
                    "trace_id": trace_id,
                    "depth": 0,
                    "visited": [],
                    "from": node_id,
                    "source": "ue_crash",
                },
                graph_id=graph_id,
            )
        except Exception as exc:
            self._record_dispatch_error(final_dir, exc)
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(
                status_code=500,
                detail=f"UE crash was stored but could not be dispatched to its agent: {type(exc).__name__}: {exc}",
            ) from exc

        return {
            "ok": True,
            "crash_id": crash_id,
            "profile_id": profile_id,
            "graph_id": graph_id,
            "node_id": node_id,
            "node_path": node_dir,
            "crash_path": final_dir,
            "file_count": archive.header.file_count,
            "pending_count": int(queued.get("pending_count") or 0),
        }

    def _require_agent_profile(self, profile_id: str) -> None:
        if self.core is None:
            raise HTTPException(status_code=503, detail="UE crash receiver is not attached to the AgentPark runtime")
        document = self.core.profile_api.list_agent_profiles()
        profiles = document.get("profiles") if isinstance(document, dict) else None
        profile = next(
            (
                item
                for item in profiles or []
                if isinstance(item, dict) and str(item.get("id") or "").strip() == profile_id
            ),
            None,
        )
        if profile is None:
            raise HTTPException(status_code=404, detail=f"agent profile not found: {profile_id}")
        if str(profile.get("node_type_id") or "").strip() != "agent_node":
            raise HTTPException(status_code=400, detail=f"UE crash profile must create an Agent node: {profile_id}")

    def _rollback_created_node(self, graph_id: str, node_id: str, node_dir: str) -> None:
        try:
            self.core.runtime_events.remove_source_rules(graph_id, node_id)
        except Exception:
            pass
        try:
            self.core.graph_runtime._unregister_scheduled_node(graph_id, node_id)
        except Exception:
            pass
        shutil.rmtree(node_dir, ignore_errors=True)

    @staticmethod
    def _record_dispatch_error(crash_dir: str, exc: Exception) -> None:
        manifest_path = os.path.join(crash_dir, "manifest.json")
        try:
            with open(manifest_path, "r", encoding="utf-8") as handle:
                metadata = json.load(handle)
            if not isinstance(metadata, dict):
                return
            metadata["dispatch_error"] = f"{type(exc).__name__}: {exc}"
            metadata["dispatch_failed_at"] = datetime.now(timezone.utc).isoformat()
            with open(manifest_path, "w", encoding="utf-8", newline="\n") as handle:
                json.dump(metadata, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
        except (OSError, ValueError):
            return

    @staticmethod
    def _content_length(request: Request) -> int | None:
        raw = str(request.headers.get("content-length") or "").strip()
        if not raw:
            return None
        try:
            value = int(raw)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="Content-Length must be an integer") from exc
        if value < 0:
            raise HTTPException(status_code=400, detail="Content-Length must not be negative")
        return value

    @staticmethod
    def _crash_id(value: str) -> str:
        crash_id = str(value or "").strip()
        if not CRASH_ID_PATTERN.fullmatch(crash_id):
            raise HTTPException(status_code=400, detail="UE crash directory name is not a safe crash id")
        return crash_id

    @staticmethod
    def _archive_filename(value: str, crash_id: str) -> str:
        expected = f"{crash_id}.uecrash"
        if str(value or "").strip() != expected:
            raise HTTPException(status_code=400, detail="UE crash archive file name does not match its crash id")
        return expected

    @staticmethod
    def _profile_id(value: object) -> str:
        profile_id = str(value or "").strip()
        if not profile_id:
            raise HTTPException(status_code=400, detail="ProfileID is required")
        if not PROFILE_ID_PATTERN.fullmatch(profile_id):
            raise HTTPException(status_code=400, detail="ProfileID contains unsupported characters")
        return profile_id

    def _graph_id(self, value: object) -> str:
        raw = str(value or "default").strip() or "default"
        graph_id = self.core.graph_runtime._sanitize_graph_id(raw)
        if graph_id != raw:
            raise HTTPException(status_code=400, detail="GraphID contains unsupported characters")
        return graph_id

    @staticmethod
    def _node_id(crash_id: str) -> str:
        readable = re.sub(r"[^A-Za-z0-9_-]+", "_", crash_id).strip("_")[-48:] or "crash"
        digest = hashlib.sha256(crash_id.encode("utf-8")).hexdigest()[:12]
        return f"UECrash_{readable}_{digest}"


def parse_ue_crash_archive(payload: bytes) -> UeCrashArchive:
    if not isinstance(payload, bytes) or not payload:
        raise UeCrashArchiveError("UE crash payload is empty")
    try:
        decompressor = zlib.decompressobj()
        data = decompressor.decompress(payload, MAX_UNCOMPRESSED_SIZE + 1)
    except zlib.error as exc:
        raise UeCrashArchiveError(f"UE crash payload is not valid zlib data: {exc}") from exc
    if len(data) > MAX_UNCOMPRESSED_SIZE:
        raise UeCrashArchiveError("UE crash archive exceeds the uncompressed size limit")
    if not decompressor.eof:
        if decompressor.unconsumed_tail:
            raise UeCrashArchiveError("UE crash archive exceeds the uncompressed size limit")
        raise UeCrashArchiveError("UE crash payload contains a truncated zlib stream")
    if decompressor.unused_data:
        raise UeCrashArchiveError("UE crash payload contains trailing compressed data")
    if len(data) < HEADER_SIZE or data[: len(CR1_MARKER)] != CR1_MARKER:
        raise UeCrashArchiveError("UE crash archive is missing a valid CR1 header")

    offset = len(CR1_MARKER)
    directory_name, offset = _read_ansi_field(data, offset, "directory name")
    file_name, offset = _read_ansi_field(data, offset, "archive file name")
    uncompressed_size, offset = _read_int32(data, offset, "uncompressed size")
    file_count, offset = _read_int32(data, offset, "file count")
    if uncompressed_size != len(data):
        raise UeCrashArchiveError(
            f"UE crash archive size mismatch: header={uncompressed_size}, actual={len(data)}"
        )
    if file_count < 0 or file_count > MAX_FILE_COUNT:
        raise UeCrashArchiveError(f"UE crash archive file count is invalid: {file_count}")

    files: list[UeCrashArchiveFile] = []
    seen_names: set[str] = set()
    for expected_index in range(file_count):
        index, offset = _read_int32(data, offset, "file index")
        if index != expected_index:
            raise UeCrashArchiveError(
                f"UE crash archive file index mismatch: expected={expected_index}, actual={index}"
            )
        source_name, offset = _read_ansi_field(data, offset, "file name")
        safe_name = _sanitize_filename(source_name)
        if safe_name.casefold() in seen_names:
            raise UeCrashArchiveError(f"UE crash archive contains duplicate file name: {safe_name}")
        seen_names.add(safe_name.casefold())
        file_size, offset = _read_int32(data, offset, "file size")
        if file_size < 0 or file_size > MAX_FILE_SIZE:
            raise UeCrashArchiveError(f"UE crash archive file size is invalid: {file_size}")
        end = offset + file_size
        if end > len(data):
            raise UeCrashArchiveError(f"UE crash archive file is truncated: {safe_name}")
        files.append(UeCrashArchiveFile(index=index, name=safe_name, data=data[offset:end]))
        offset = end
    if offset != len(data):
        raise UeCrashArchiveError(f"UE crash archive has {len(data) - offset} trailing bytes")
    return UeCrashArchive(
        header=UeCrashArchiveHeader(directory_name, file_name, uncompressed_size, file_count),
        files=tuple(files),
    )


def _sanitize_filename(value: str) -> str:
    name = str(value or "").strip()
    if not name or name in {".", ".."} or os.path.basename(name) != name or "/" in name or "\\" in name:
        raise UeCrashArchiveError(f"UE crash archive file name is unsafe: {name!r}")
    if not re.fullmatch(r"[^\x00-\x1f\x7f]+", name):
        raise UeCrashArchiveError(f"UE crash archive file name contains control characters: {name!r}")
    return name


def _read_ansi_field(data: bytes, offset: int, label: str) -> tuple[str, int]:
    length, offset = _read_int32(data, offset, f"{label} length")
    if length != ANSI_FIELD_WIDTH:
        raise UeCrashArchiveError(f"UE crash archive {label} field width is invalid: {length}")
    end = offset + length
    if end > len(data):
        raise UeCrashArchiveError(f"UE crash archive {label} field is truncated")
    return data[offset:end].split(b"\0", 1)[0].decode("latin-1"), end


def _read_int32(data: bytes, offset: int, label: str) -> tuple[int, int]:
    end = offset + 4
    if end > len(data):
        raise UeCrashArchiveError(f"UE crash archive {label} is truncated")
    return struct.unpack_from("<i", data, offset)[0], end


def get_api_routes(context):
    if context.core is None:
        raise RuntimeError("Unreal Engine server API requires the AgentPark backend core")
    receiver = UeCrashReceiver(context.runtime_root, context.core)
    return [
        {
            "method": "post",
            "path": "/api/ue/crashes/{profile_id}",
            "handler": receiver.receive_crash,
            "name": "unreal_engine_receive_crash_for_profile",
        },
        {
            "method": "post",
            "path": "/api/ue/crashes",
            "handler": receiver.receive_crash,
            "name": "unreal_engine_receive_crash",
        }
    ]
