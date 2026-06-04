import json
import os
import shutil
import subprocess
import time
from collections import Counter


_READ_FILE_MAX_CHARS = 300000
_RG_OVERVIEW_TIMEOUT_SEC = 20
_RG_STOP_WAIT_SEC = 0.5

_DEFAULT_SKIP_DIRS = {
    ".git",
    ".svn",
    ".hg",
    ".vs",
    ".idea",
    ".vscode",
    ".pytest_cache",
    ".mypy_cache",
    ".tox",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "build",
    "dist",
    "out",
    "coverage",
    "Binaries",
    "Intermediate",
    "DerivedDataCache",
    "site-packages",
    "Lib",
}


def _resolve_root(project_root):
    root = project_root if isinstance(project_root, str) and project_root.strip() else os.getcwd()
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return None
    return root


def _resolve_limit(raw_value, default_value, hard_max):
    try:
        value = int(raw_value)
    except Exception:
        value = default_value
    return max(1, min(value, hard_max))


def _get_skip_dirs():
    return set(_DEFAULT_SKIP_DIRS)


def _safe_relpath(file_path, root):
    try:
        return os.path.relpath(file_path, root)
    except Exception:
        return file_path


def _append_rg_scope_args(cmd):
    for directory in sorted(_get_skip_dirs()):
        cmd.extend(["-g", f"!{directory}/**"])
    return cmd


def _terminate_process(proc):
    if proc is None:
        return
    if proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=_RG_STOP_WAIT_SEC)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=_RG_STOP_WAIT_SEC)
        except Exception:
            pass


def _run_rg_stream_lines(cmd, on_line, timeout_sec):
    proc = None
    timed_out = False
    stopped_early = False
    stderr_text = ""
    return_code = None
    had_output = False

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        deadline = time.monotonic() + float(timeout_sec or 0)

        while True:
            if timeout_sec and time.monotonic() >= deadline:
                timed_out = True
                break

            line = proc.stdout.readline() if proc.stdout else ""
            if line:
                had_output = True
                if on_line(line.rstrip("\r\n")):
                    stopped_early = True
                    break
                continue

            if proc.poll() is not None:
                break

            time.sleep(0.001)

    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
            "timed_out": timed_out,
            "stopped_early": stopped_early,
            "stderr": stderr_text,
            "return_code": return_code,
            "had_output": had_output,
        }
    finally:
        if proc is not None and (timed_out or stopped_early):
            _terminate_process(proc)

        if proc is not None:
            try:
                stderr_text = proc.stderr.read() if proc.stderr else ""
            except Exception:
                stderr_text = ""
            try:
                return_code = proc.wait(timeout=_RG_STOP_WAIT_SEC)
            except Exception:
                return_code = proc.poll()

    return {
        "ok": True,
        "timed_out": timed_out,
        "stopped_early": stopped_early,
        "stderr": stderr_text,
        "return_code": return_code,
        "had_output": had_output,
    }


def _iter_files_walk(root):
    skip_dirs = {name.lower() for name in _get_skip_dirs()}
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]
        for filename in files:
            yield os.path.join(current_root, filename)


def read_file(file_path, start_line=1, end_line=None):
    """
    Reads a file from the local filesystem.
    """
    try:
        if not isinstance(file_path, str) or not file_path.strip():
            return json.dumps({"file_path": file_path, "error": "Invalid file_path", "status": "error"})
        target = os.path.abspath(file_path)
        if not os.path.exists(target):
            return json.dumps({"file_path": target, "error": "File not found", "status": "error"})

        try:
            start_line = int(start_line)
        except Exception:
            start_line = 1
        if start_line < 1:
            start_line = 1

        if end_line is not None:
            try:
                end_line = int(end_line)
            except Exception:
                end_line = None
            if isinstance(end_line, int) and end_line < start_line:
                end_line = start_line

        selected_lines = []
        selected_chars = 0
        total_lines = 0
        output_truncated = False

        with open(target, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                total_lines = line_no
                if line_no < start_line:
                    continue
                if end_line is not None and line_no > end_line:
                    continue

                line_len = len(line)
                if selected_chars + line_len > _READ_FILE_MAX_CHARS:
                    remaining = _READ_FILE_MAX_CHARS - selected_chars
                    if remaining > 0:
                        selected_lines.append(line[:remaining])
                        selected_chars += remaining
                    output_truncated = True
                    break

                selected_lines.append(line)
                selected_chars += line_len

        content = "".join(selected_lines)
        if output_truncated:
            content += "\n...(truncated)...\n"

        if selected_lines:
            read_end = start_line + len(selected_lines) - 1
        else:
            read_end = min(total_lines, start_line) if total_lines else start_line
        if end_line is not None:
            read_end = min(read_end, end_line)

        payload = {
            "file_path": target,
            "content": content,
            "total_lines": total_lines,
            "read_lines": f"{start_line}-{read_end}",
            "status": "success",
        }
        if output_truncated:
            payload["output_truncated"] = True
            payload["output_char_limit"] = _READ_FILE_MAX_CHARS
        return json.dumps(payload, ensure_ascii=False)

    except Exception as e:
        return json.dumps({"file_path": file_path, "error": str(e), "status": "exception"}, ensure_ascii=False)


read_file_declaration = {
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read content from a file, with optional line range and output truncation safety for very large files.",
        "parameters": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "Absolute path to the file",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Start line number (1-based, default: 1)",
                    "default": 1,
                },
                "end_line": {
                    "type": "integer",
                    "description": "End line number (optional, default: end of file)",
                },
            },
            "required": ["file_path"],
        },
    },
}


def project_overview(project_root=None, sample_limit=120, max_scan_files=200000):
    """
    Fast project overview for LLM planning: top dirs/extensions and sample files.
    """
    try:
        root = _resolve_root(project_root)
        if not root:
            return json.dumps({"status": "error", "error": f"project_root not found: {project_root}"})

        sample_limit = _resolve_limit(sample_limit, default_value=120, hard_max=1000)
        max_scan_files = _resolve_limit(max_scan_files, default_value=200000, hard_max=1000000)

        top_dirs = Counter()
        top_exts = Counter()
        sample_files = []
        total_files = 0
        scan_capped = False

        rg_path = shutil.which("rg")
        if rg_path:
            cmd = [rg_path, "--files", "--no-messages"]
            _append_rg_scope_args(cmd)
            cmd.append(root)

            def _on_line(raw_line):
                nonlocal total_files, scan_capped
                file_path = str(raw_line or "").strip()
                if not file_path:
                    return False
                if not os.path.isabs(file_path):
                    file_path = os.path.abspath(os.path.join(root, file_path))

                total_files += 1
                rel = _safe_relpath(file_path, root)
                rel_norm = rel.replace("\\", "/")
                head = rel_norm.split("/", 1)[0] if "/" in rel_norm else "."
                ext = os.path.splitext(file_path)[1].lower() or "(no_ext)"
                top_dirs[head] += 1
                top_exts[ext] += 1
                if len(sample_files) < sample_limit:
                    sample_files.append(rel)
                if total_files >= max_scan_files:
                    scan_capped = True
                    return True
                return False

            meta = _run_rg_stream_lines(cmd, _on_line, timeout_sec=_RG_OVERVIEW_TIMEOUT_SEC)
            return_code = meta.get("return_code")
            rg_ok = bool(meta.get("ok")) and (meta.get("timed_out") or return_code in (0, 1, None))
            if rg_ok:
                if meta.get("timed_out"):
                    scan_capped = True
                return json.dumps(
                    {
                        "status": "success",
                        "engine": "rg",
                        "project_root": root,
                        "total_files_scanned": total_files,
                        "scan_capped": scan_capped,
                        "top_directories": [{"name": name, "count": count} for name, count in top_dirs.most_common(20)],
                        "top_extensions": [{"ext": ext, "count": count} for ext, count in top_exts.most_common(20)],
                        "sample_files": sample_files,
                    },
                    ensure_ascii=False,
                )

        for file_path in _iter_files_walk(root):
            total_files += 1
            rel = _safe_relpath(file_path, root)
            rel_norm = rel.replace("\\", "/")
            head = rel_norm.split("/", 1)[0] if "/" in rel_norm else "."
            ext = os.path.splitext(file_path)[1].lower() or "(no_ext)"
            top_dirs[head] += 1
            top_exts[ext] += 1
            if len(sample_files) < sample_limit:
                sample_files.append(rel)
            if total_files >= max_scan_files:
                scan_capped = True
                break

        return json.dumps(
            {
                "status": "success",
                "engine": "python",
                "project_root": root,
                "total_files_scanned": total_files,
                "scan_capped": scan_capped,
                "top_directories": [{"name": name, "count": count} for name, count in top_dirs.most_common(20)],
                "top_extensions": [{"ext": ext, "count": count} for ext, count in top_exts.most_common(20)],
                "sample_files": sample_files,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"status": "exception", "error": str(e)}, ensure_ascii=False)


project_overview_declaration = {
    "type": "function",
    "function": {
        "name": "project_overview",
        "description": "Quickly summarize project structure (top dirs, extensions, sample files) for planning without full slow tree listing.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "Project root directory. Defaults to current working directory.",
                },
                "sample_limit": {
                    "type": "integer",
                    "description": "Number of sample relative paths to return (1-1000, default 120).",
                    "default": 120,
                },
                "max_scan_files": {
                    "type": "integer",
                    "description": "Maximum files to scan before early stop (1-1000000, default 200000).",
                    "default": 200000,
                },
            },
        },
    },
}

