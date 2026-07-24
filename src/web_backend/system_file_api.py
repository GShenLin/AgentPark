import mimetypes
import os
import shutil
import subprocess
import uuid
from urllib.parse import unquote

from fastapi import File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse

from src.file_transaction import atomic_write_text
from src.message_protocol import build_resource_part

from .request_access import is_local_request
from .runtime_paths import _get_graphs_dir, _get_runtime_root


class FileSystemApiMixin:
    _MAX_UPLOAD_BYTES = 256 * 1024 * 1024

    def _sanitize_upload_trace_id(self, value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return uuid.uuid4().hex
        safe = "".join(ch for ch in raw if ch.isalnum() or ch in {"-", "_"})
        return safe[:64] or uuid.uuid4().hex

    def _upload_root_dir(self, trace_id: str) -> str:
        path = os.path.join(_get_graphs_dir(), "uploads", trace_id)
        os.makedirs(path, exist_ok=True)
        return path

    def _file_api_root(self) -> str:
        return os.path.abspath(_get_runtime_root())

    def _resolve_file_api_path(self, value: object, *, default_to_runtime_root: bool = False) -> str:
        raw_path = str(value or "").strip()
        if not raw_path:
            return self._file_api_root() if default_to_runtime_root else ""

        raw_path = self._normalize_local_path(raw_path)

        if os.path.isabs(raw_path):
            resolved_path = os.path.abspath(raw_path)
        else:
            resolved_path = os.path.abspath(os.path.join(self._file_api_root(), raw_path))
        return resolved_path

    def _normalize_local_path(self, raw_path: str) -> str:
        if raw_path.startswith("file://"):
            raw_path = unquote(raw_path[7:])
            if os.name == "nt" and len(raw_path) >= 3 and raw_path[0] == "/" and raw_path[2] == ":":
                raw_path = raw_path[1:]
        return raw_path

    def _sanitize_upload_name(self, value: object) -> str:
        raw_name = os.path.basename(str(value or "").strip())
        stem, ext = os.path.splitext(raw_name)
        safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in stem).strip("._")
        safe_stem = safe_stem or "upload"
        safe_ext = "".join(ch for ch in ext if ch.isalnum() or ch == ".")[:16]
        if safe_ext and not safe_ext.startswith("."):
            safe_ext = f".{safe_ext}"
        return f"{safe_stem}{safe_ext}"

    def upload_files(self, files: list[UploadFile] = File(...), trace_id: str = Form("")):
        upload_list = [item for item in (files or []) if item is not None]
        if not upload_list:
            raise HTTPException(status_code=400, detail="files are required")

        safe_trace_id = self._sanitize_upload_trace_id(trace_id)
        upload_dir = self._upload_root_dir(safe_trace_id)
        results: list[dict] = []

        for upload in upload_list:
            safe_name = self._sanitize_upload_name(upload.filename)
            stem, ext = os.path.splitext(safe_name)
            save_name = f"{stem}_{uuid.uuid4().hex[:8]}{ext}"
            save_path = os.path.join(upload_dir, save_name)
            total_bytes = 0
            try:
                with open(save_path, "wb") as out:
                    while True:
                        chunk = upload.file.read(1024 * 1024)
                        if not chunk:
                            break
                        total_bytes += len(chunk)
                        if total_bytes > self._MAX_UPLOAD_BYTES:
                            raise HTTPException(
                                status_code=413,
                                detail=f"upload exceeds {self._MAX_UPLOAD_BYTES // (1024 * 1024)}MB limit",
                            )
                        out.write(chunk)
            except HTTPException:
                if os.path.exists(save_path):
                    try:
                        os.remove(save_path)
                    except Exception:
                        pass
                raise
            finally:
                try:
                    upload.file.close()
                except Exception:
                    pass

            part = build_resource_part(
                uri=save_path,
                kind="",
                mime=str(upload.content_type or "").strip().lower(),
                name=str(upload.filename or safe_name),
                source="web_upload",
            )
            resource = part.get("resource") if isinstance(part, dict) else {}
            resource_obj = resource if isinstance(resource, dict) else {}
            results.append(
                {
                    "path": save_path,
                    "name": str(resource_obj.get("name") or upload.filename or safe_name),
                    "kind": str(resource_obj.get("kind") or "file"),
                    "mime": str(resource_obj.get("mime") or upload.content_type or "").strip().lower(),
                    "size": total_bytes,
                    "source": str(resource_obj.get("source") or "web_upload"),
                }
            )

        return {"files": results, "trace_id": safe_trace_id}

    def list_files(self, path: str = "", search: str = ""):
        try:
            target_path = self._resolve_file_api_path(path, default_to_runtime_root=True)

            if not target_path:
                raise HTTPException(status_code=400, detail="Invalid path")

            if not os.path.exists(target_path):
                raise HTTPException(status_code=404, detail="Path not found")
            if not os.path.isdir(target_path):
                raise HTTPException(status_code=400, detail="Path is not a directory")

            items = []
            if search and search.strip():
                search_term = search.strip().lower()
                ignored_dirs = {".git", "node_modules", "__pycache__", ".idea", ".vscode", "dist", "build", "coverage"}
                count = 0
                max_items = 500

                try:
                    rg_path = shutil.which("rg")
                    if rg_path:
                        cmd = [rg_path, "--files", "--no-messages"]
                        for directory in sorted(ignored_dirs):
                            cmd.extend(["-g", f"!{directory}/**"])
                        cmd.append(target_path)

                        proc = subprocess.Popen(
                            cmd,
                            stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE,
                            text=True,
                            encoding="utf-8",
                            errors="replace",
                        )
                        try:
                            for raw_line in proc.stdout:
                                file_path = str(raw_line or "").strip()
                                if not file_path:
                                    continue
                                if search_term not in os.path.basename(file_path).lower():
                                    continue

                                if not os.path.isabs(file_path):
                                    file_path = os.path.abspath(os.path.join(target_path, file_path))

                                try:
                                    rel_path = os.path.relpath(file_path, target_path)
                                except ValueError:
                                    rel_path = os.path.basename(file_path)

                                items.append({"name": rel_path, "path": file_path, "type": "file"})
                                count += 1
                                if count >= max_items:
                                    break
                        finally:
                            try:
                                proc.terminate()
                            except Exception:
                                pass
                            try:
                                proc.wait(timeout=0.2)
                            except Exception:
                                pass
                    else:
                        for root, dirs, files in os.walk(target_path):
                            dirs[:] = [d for d in dirs if d not in ignored_dirs]

                            for name in files:
                                if search_term in name.lower():
                                    full_path = os.path.join(root, name)
                                    try:
                                        rel_path = os.path.relpath(full_path, target_path)
                                    except ValueError:
                                        rel_path = name

                                    items.append({"name": rel_path, "path": full_path, "type": "file"})
                                    count += 1

                            if count >= max_items:
                                break
                except PermissionError:
                    pass
                except Exception as e:
                    print(f"Error during search walk: {e}")

            else:
                try:
                    with os.scandir(target_path) as it:
                        for entry in it:
                            try:
                                is_dir = entry.is_dir()
                                items.append({"name": entry.name, "path": entry.path, "type": "dir" if is_dir else "file"})
                            except Exception:
                                continue
                except PermissionError:
                    raise HTTPException(status_code=403, detail="Permission denied")
                except OSError as e:
                    raise HTTPException(status_code=500, detail=f"OS Error: {str(e)}")

            items.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"].lower()))

            return {"files": items, "current_path": target_path}
        except HTTPException:
            raise
        except Exception as e:
            print(f"Unhandled error in list_files: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def read_file(self, path: str):
        try:
            resolved_path = self._resolve_file_api_path(path)
            if not resolved_path or not os.path.exists(resolved_path):
                raise HTTPException(status_code=404, detail="File not found")
            if not os.path.isfile(resolved_path):
                raise HTTPException(status_code=400, detail="Not a file")

            max_size = 1024 * 1024
            size = os.path.getsize(resolved_path)
            if size > max_size:
                with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(max_size)
                    content += "\n\n... (File truncated due to size limit) ..."
            else:
                with open(resolved_path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

            return {"content": content, "path": resolved_path}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def raw_file(self, path: str, download: bool = False):
        resolved_path = self._resolve_file_api_path(path)
        if not resolved_path:
            raise HTTPException(status_code=400, detail="path is required")
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="file not found")
        if not os.path.isfile(resolved_path):
            raise HTTPException(status_code=400, detail="path is not a file")

        media_type, _ = mimetypes.guess_type(resolved_path)
        if not media_type:
            media_type = "application/octet-stream"

        filename = os.path.basename(resolved_path)
        if bool(download):
            return FileResponse(resolved_path, media_type=media_type, filename=filename)
        return FileResponse(resolved_path, media_type=media_type)

    def open_file(self, payload: dict | None = None, request: Request = None):
        if not is_local_request(request):
            raise HTTPException(status_code=403, detail="opening local files is only available from the server machine")

        resolved_path = self._resolve_file_api_path((payload or {}).get("path"))
        if not resolved_path:
            raise HTTPException(status_code=400, detail="path is required")
        if not os.path.exists(resolved_path):
            raise HTTPException(status_code=404, detail="file not found")
        if not os.path.isfile(resolved_path):
            raise HTTPException(status_code=400, detail="path is not a file")

        try:
            self._launch_local_file(resolved_path)
        except Exception as exc:
            raise HTTPException(status_code=500, detail=f"failed to open local file: {str(exc)}")
        return {"ok": True, "path": resolved_path}

    @staticmethod
    def _launch_local_file(path: str) -> None:
        if os.name != "nt":
            raise RuntimeError("opening local files is only supported on Windows")
        os.startfile(os.path.normpath(path))

    def select_folder(self, payload: dict | None = None):
        initial_path = str((payload or {}).get("initial_path") or "").strip()
        initial_dir = self._file_api_root()
        if initial_path:
            resolved_initial_path = self._resolve_file_api_path(initial_path, default_to_runtime_root=True)
            if os.path.isdir(resolved_initial_path):
                initial_dir = resolved_initial_path

        root = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askdirectory(
                parent=root,
                initialdir=initial_dir,
                title="Select node working path",
                mustexist=True,
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to open folder selector: {str(e)}")
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

        if not selected:
            return {"ok": True, "path": ""}
        selected_path = self._resolve_file_api_path(selected)
        if not os.path.isdir(selected_path):
            raise HTTPException(status_code=400, detail="selected path is not a directory")
        return {"ok": True, "path": selected_path}

    def select_file(self, payload: dict | None = None):
        initial_path = str((payload or {}).get("initial_path") or "").strip()
        initial_dir = self._file_api_root()
        initial_file = ""
        if initial_path:
            resolved_initial_path = self._resolve_file_api_path(initial_path, default_to_runtime_root=True)
            if os.path.isdir(resolved_initial_path):
                initial_dir = resolved_initial_path
            elif os.path.isfile(resolved_initial_path):
                initial_dir = os.path.dirname(resolved_initial_path)
                initial_file = os.path.basename(resolved_initial_path)
            else:
                candidate_dir = os.path.dirname(resolved_initial_path)
                if os.path.isdir(candidate_dir):
                    initial_dir = candidate_dir

        root = None
        try:
            import tkinter as tk
            from tkinter import filedialog

            root = tk.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            selected = filedialog.askopenfilename(
                parent=root,
                initialdir=initial_dir,
                initialfile=initial_file,
                title="Select context file",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"failed to open file selector: {str(e)}")
        finally:
            if root is not None:
                try:
                    root.destroy()
                except Exception:
                    pass

        if not selected:
            return {"ok": True, "path": ""}
        selected_path = self._resolve_file_api_path(selected)
        if not os.path.isfile(selected_path):
            raise HTTPException(status_code=400, detail="selected path is not a file")
        return {"ok": True, "path": selected_path}

    def write_file(self, payload: dict):
        path = self._resolve_file_api_path((payload or {}).get("path"))
        content = (payload or {}).get("content")

        if not path:
            raise HTTPException(status_code=400, detail="path is required")

        try:
            atomic_write_text(path, content if content is not None else "")
            return {"ok": True, "path": path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def rename_file(self, payload: dict):
        old_path = self._resolve_file_api_path((payload or {}).get("old_path"))
        new_path = self._resolve_file_api_path((payload or {}).get("new_path"))

        if not old_path:
            raise HTTPException(status_code=400, detail="old_path is required")
        if not new_path:
            raise HTTPException(status_code=400, detail="new_path is required")

        try:
            if not os.path.exists(old_path):
                raise HTTPException(status_code=404, detail="source path not found")
            if os.path.exists(new_path):
                raise HTTPException(status_code=409, detail="target path already exists")

            parent_dir = os.path.dirname(new_path)
            if parent_dir and not os.path.exists(parent_dir):
                raise HTTPException(status_code=400, detail="target parent directory does not exist")

            os.rename(old_path, new_path)
            return {"ok": True, "old_path": old_path, "new_path": new_path}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def delete_file(self, payload: dict):
        path = self._resolve_file_api_path((payload or {}).get("path"))
        recursive = bool((payload or {}).get("recursive", True))

        if not path:
            raise HTTPException(status_code=400, detail="path is required")

        try:
            if not os.path.exists(path):
                raise HTTPException(status_code=404, detail="path not found")

            if os.path.isdir(path):
                if recursive:
                    shutil.rmtree(path)
                else:
                    os.rmdir(path)
            else:
                os.remove(path)
            return {"ok": True, "path": path}
        except HTTPException:
            raise
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))


__all__ = ["FileSystemApiMixin"]
