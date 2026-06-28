from .domain_base import DomainBase
from .shared import *
import subprocess
import mimetypes
import time
import uuid
from fastapi.responses import FileResponse
from fastapi import File, Form, UploadFile
from src.provider_options import build_provider_support_list
from src.message_protocol import build_resource_part


class SystemApiDomain(DomainBase):
    _MAX_UPLOAD_BYTES = 256 * 1024 * 1024

    def _sanitize_upload_trace_id(self, value: object) -> str:
        raw = str(value or "").strip()
        if not raw:
            return uuid.uuid4().hex
        safe = "".join(ch for ch in raw if ch.isalnum() or ch in {"-", "_"})
        return safe[:64] or uuid.uuid4().hex

    def _upload_root_dir(self, trace_id: str) -> str:
        path = os.path.join(_get_runtime_root(), "memories", "uploads", trace_id)
        os.makedirs(path, exist_ok=True)
        return path

    def _sanitize_upload_name(self, value: object) -> str:
        raw_name = os.path.basename(str(value or "").strip())
        stem, ext = os.path.splitext(raw_name)
        safe_stem = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "_" for ch in stem).strip("._")
        safe_stem = safe_stem or "upload"
        safe_ext = "".join(ch for ch in ext if ch.isalnum() or ch == ".")[:16]
        if safe_ext and not safe_ext.startswith("."):
            safe_ext = f".{safe_ext}"
        return f"{safe_stem}{safe_ext}"

    def restart_server(self):
        self.request_webui_close({"reason": "restart"})
        runtime_root = _get_runtime_root()
        restart_path = os.path.join(runtime_root, "Restart.bat")
        if not os.path.isfile(restart_path):
            raise HTTPException(status_code=404, detail="Restart.bat not found")
        try:
            if os.name == "nt":
                subprocess.Popen(
                    ["cmd.exe", "/c", "start", "AITools Restart", restart_path],
                    cwd=runtime_root,
                    close_fds=True,
                    creationflags=subprocess.CREATE_NEW_PROCESS_GROUP,
                )
            else:
                subprocess.Popen([restart_path], cwd=runtime_root, start_new_session=True)
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))
        return {"ok": True}

    def request_webui_close(self, payload: dict | None = None):
        reason = str((payload or {}).get("reason") or "restart").strip() or "restart"
        token = uuid.uuid4().hex
        self.core.webui_close_signal = {
            "token": token,
            "requested_at": time.time(),
            "reason": reason,
        }
        return {"ok": True, "token": token, "reason": reason}

    def get_webui_close_signal(self):
        signal = getattr(self.core, "webui_close_signal", None)
        if not isinstance(signal, dict):
            return {"close": False, "token": "", "reason": ""}
        requested_at = float(signal.get("requested_at") or 0)
        if requested_at <= 0:
            return {"close": False, "token": "", "reason": ""}
        if time.time() - requested_at > 30:
            return {"close": False, "token": "", "reason": ""}
        return {
            "close": True,
            "token": str(signal.get("token") or ""),
            "reason": str(signal.get("reason") or "restart"),
        }

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
            target_path = path if path and path.strip() else _get_runtime_root()

            # Basic validation
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

                                items.append({
                                    "name": rel_path,
                                    "path": file_path,
                                    "type": "file"
                                })
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
                            # Filter dirs in-place to avoid traversing ignored ones
                            dirs[:] = [d for d in dirs if d not in ignored_dirs]

                            for name in files:
                                if search_term in name.lower():
                                    # Use relative path for display name in search results
                                    full_path = os.path.join(root, name)
                                    try:
                                        rel_path = os.path.relpath(full_path, target_path)
                                    except ValueError:
                                        rel_path = name

                                    items.append({
                                        "name": rel_path,
                                        "path": full_path,
                                        "type": "file"
                                    })
                                    count += 1

                            if count >= max_items:
                                break
                except PermissionError:
                    pass # Ignore permission errors during search
                except Exception as e:
                    # Log error but return what we have so far
                    print(f"Error during search walk: {e}")

            else:
                try:
                    with os.scandir(target_path) as it:
                        for entry in it:
                            try:
                                is_dir = entry.is_dir()
                                items.append({
                                    "name": entry.name,
                                    "path": entry.path,
                                    "type": "dir" if is_dir else "file"
                                })
                            except Exception:
                                continue
                except PermissionError:
                     raise HTTPException(status_code=403, detail="Permission denied")
                except OSError as e:
                     raise HTTPException(status_code=500, detail=f"OS Error: {str(e)}")

            # Sort: directories first, then by name
            items.sort(key=lambda x: (0 if x["type"] == "dir" else 1, x["name"].lower()))

            return {"files": items, "current_path": target_path}
        except HTTPException:
            raise
        except Exception as e:
            # Catch-all for any other unexpected errors to prevent server crash
            print(f"Unhandled error in list_files: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    def read_file(self, path: str):
        try:
            if not path or not os.path.exists(path):
                raise HTTPException(status_code=404, detail="File not found")
            if not os.path.isfile(path):
                raise HTTPException(status_code=400, detail="Not a file")

            # Limit file size to avoid crashing
            max_size = 1024 * 1024  # 1MB
            size = os.path.getsize(path)
            if size > max_size:
                 with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read(max_size)
                    content += "\n\n... (File truncated due to size limit) ..."
            else:
                with open(path, "r", encoding="utf-8", errors="replace") as f:
                    content = f.read()

            return {"content": content, "path": path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def raw_file(self, path: str, download: bool = False):
        raw_path = str(path or "").strip()
        if not raw_path:
            raise HTTPException(status_code=400, detail="path is required")

        if raw_path.startswith("file://"):
            raw_path = raw_path[7:]

        if os.path.isabs(raw_path):
            resolved_path = raw_path
        else:
            resolved_path = os.path.join(_get_runtime_root(), raw_path)

        resolved_path = os.path.abspath(resolved_path)
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

    def select_folder(self, payload: dict | None = None):
        initial_path = str((payload or {}).get("initial_path") or "").strip()
        initial_dir = initial_path if initial_path and os.path.isdir(initial_path) else _get_runtime_root()

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

        return {"ok": True, "path": str(selected or "")}

    def write_file(self, payload: dict):
        path = (payload or {}).get("path")
        content = (payload or {}).get("content")

        if not path:
             raise HTTPException(status_code=400, detail="path is required")

        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content if content is not None else "")
            return {"ok": True, "path": path}
        except Exception as e:
            raise HTTPException(status_code=500, detail=str(e))

    def rename_file(self, payload: dict):
        old_path = str((payload or {}).get("old_path") or "").strip()
        new_path = str((payload or {}).get("new_path") or "").strip()

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
        path = str((payload or {}).get("path") or "").strip()
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

    def list_providers(self):
        return {"providers": build_provider_support_list()}

__all__ = ["SystemApiDomain"]
