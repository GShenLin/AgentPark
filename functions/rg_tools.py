import fnmatch
import json
import os
import re
import shutil
import subprocess
import time


_RG_LINE_RE = re.compile(r"^(.*?):(\d+):(.*)$")
_RG_TIMEOUT_SEC = 15
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


def _normalize_globs(raw_globs):
    if not isinstance(raw_globs, list):
        return []
    out = []
    seen = set()
    for item in raw_globs:
        value = str(item or "").strip()
        if not value:
            continue
        if value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def _safe_relpath(path, root):
    try:
        return os.path.relpath(path, root)
    except Exception:
        return path


def _normalize_rel_path(path):
    return str(path or "").replace("\\", "/")


def _match_any_glob(rel_path, globs):
    if not globs:
        return False
    rel_norm = _normalize_rel_path(rel_path)
    base = os.path.basename(rel_norm)
    for pattern in globs:
        if fnmatch.fnmatch(rel_norm, pattern) or fnmatch.fnmatch(base, pattern):
            return True
    return False


def _path_allowed(rel_path, include_globs, exclude_globs):
    if include_globs and not _match_any_glob(rel_path, include_globs):
        return False
    if exclude_globs and _match_any_glob(rel_path, exclude_globs):
        return False
    return True


def _terminate_process(proc):
    if proc is None or proc.poll() is not None:
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


def _iter_files_fallback(root):
    skip_dirs = {name.lower() for name in _DEFAULT_SKIP_DIRS}
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]
        for filename in files:
            yield os.path.join(current_root, filename)


def _append_rg_globs(cmd, include_globs, exclude_globs):
    for pattern in include_globs:
        cmd.extend(["-g", pattern])
    for pattern in exclude_globs:
        cmd.extend(["-g", f"!{pattern}"])
    for directory in sorted(_DEFAULT_SKIP_DIRS):
        cmd.extend(["-g", f"!{directory}/**"])


def _parse_rg_line(raw_line):
    if not isinstance(raw_line, str) or not raw_line:
        return None
    m = _RG_LINE_RE.match(raw_line)
    if not m:
        return None
    file_path = m.group(1)
    try:
        line_number = int(m.group(2))
    except Exception:
        return None
    line_text = m.group(3)
    return file_path, line_number, line_text


def rg_search_text(
    query,
    project_root=None,
    include_globs=None,
    exclude_globs=None,
    case_sensitive=False,
    fixed_strings=True,
    max_results=200,
):
    try:
        if not isinstance(query, str) or not query.strip():
            return json.dumps({"status": "error", "error": "query is required"}, ensure_ascii=False)

        root = _resolve_root(project_root)
        if not root:
            return json.dumps({"status": "error", "error": f"project_root not found: {project_root}"}, ensure_ascii=False)

        include_globs = _normalize_globs(include_globs)
        exclude_globs = _normalize_globs(exclude_globs)
        limit = _resolve_limit(max_results, default_value=200, hard_max=5000)
        case_sensitive = bool(case_sensitive)
        fixed_strings = bool(fixed_strings)
        stripped_query = query.strip()

        rg_path = shutil.which("rg")
        if rg_path:
            matches = []
            cmd = [rg_path, "-n", "--color", "never", "--no-messages", "--max-columns", "400", "--max-columns-preview"]
            if fixed_strings:
                cmd.append("-F")
            if not case_sensitive:
                cmd.append("-i")
            _append_rg_globs(cmd, include_globs, exclude_globs)
            cmd.extend([stripped_query, root])

            def _on_line(raw_line):
                parsed = _parse_rg_line(raw_line)
                if not parsed:
                    return False
                file_path, line_number, line_text = parsed
                if not os.path.isabs(file_path):
                    file_path = os.path.abspath(os.path.join(root, file_path))

                matches.append(
                    {
                        "file_path": file_path,
                        "relative_path": _safe_relpath(file_path, root),
                        "line": line_number,
                        "match": str(line_text or "").strip()[:400],
                    }
                )
                return len(matches) >= limit

            meta = _run_rg_stream_lines(cmd, _on_line, timeout_sec=_RG_TIMEOUT_SEC)
            if not meta.get("ok"):
                return json.dumps(
                    {
                        "status": "error",
                        "engine": "rg",
                        "query": stripped_query,
                        "project_root": root,
                        "error": str(meta.get("error") or "failed to execute rg"),
                    },
                    ensure_ascii=False,
                )

            return_code = meta.get("return_code")
            if not meta.get("timed_out") and isinstance(return_code, int) and return_code not in (0, 1):
                return json.dumps(
                    {
                        "status": "error",
                        "engine": "rg",
                        "query": stripped_query,
                        "project_root": root,
                        "return_code": return_code,
                        "stderr": str(meta.get("stderr") or ""),
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "status": "success",
                    "engine": "rg",
                    "query": stripped_query,
                    "project_root": root,
                    "fixed_strings": fixed_strings,
                    "case_sensitive": case_sensitive,
                    "matches": matches,
                    "truncated": len(matches) >= limit or bool(meta.get("timed_out")),
                    "timed_out": bool(meta.get("timed_out")),
                },
                ensure_ascii=False,
            )

        flags = 0 if case_sensitive else re.IGNORECASE
        try:
            compiled = re.compile(re.escape(stripped_query) if fixed_strings else stripped_query, flags)
        except re.error as e:
            return json.dumps(
                {
                    "status": "error",
                    "engine": "python",
                    "error": f"invalid regex: {str(e)}",
                },
                ensure_ascii=False,
            )

        matches = []
        searched_files = 0
        for file_path in _iter_files_fallback(root):
            rel_path = _safe_relpath(file_path, root)
            if not _path_allowed(rel_path, include_globs, exclude_globs):
                continue
            searched_files += 1
            try:
                with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                    for line_no, line in enumerate(f, start=1):
                        if compiled.search(line):
                            matches.append(
                                {
                                    "file_path": file_path,
                                    "relative_path": rel_path,
                                    "line": line_no,
                                    "match": line.strip()[:400],
                                }
                            )
                            if len(matches) >= limit:
                                return json.dumps(
                                    {
                                        "status": "success",
                                        "engine": "python",
                                        "query": stripped_query,
                                        "project_root": root,
                                        "fixed_strings": fixed_strings,
                                        "case_sensitive": case_sensitive,
                                        "searched_files": searched_files,
                                        "matches": matches,
                                        "truncated": True,
                                    },
                                    ensure_ascii=False,
                                )
            except Exception:
                continue

        return json.dumps(
            {
                "status": "success",
                "engine": "python",
                "query": stripped_query,
                "project_root": root,
                "fixed_strings": fixed_strings,
                "case_sensitive": case_sensitive,
                "searched_files": searched_files,
                "matches": matches,
                "truncated": False,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"status": "exception", "error": str(e)}, ensure_ascii=False)


rg_search_text_declaration = {
    "type": "function",
    "function": {
        "name": "rg_search_text",
        "description": "Search text in project files with ripgrep semantics (rg). Prefer this over shell grep/findstr.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Query text or regex pattern to search.",
                },
                "project_root": {
                    "type": "string",
                    "description": "Project root directory. Defaults to current working directory.",
                },
                "include_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional include globs, e.g. ['*.py', 'src/**'].",
                },
                "exclude_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional exclude globs, e.g. ['dist/**', 'build/**'].",
                },
                "case_sensitive": {
                    "type": "boolean",
                    "description": "Case-sensitive search (default false).",
                    "default": False,
                },
                "fixed_strings": {
                    "type": "boolean",
                    "description": "Treat query as literal text instead of regex (default true).",
                    "default": True,
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum matches to return (1-5000, default 200).",
                    "default": 200,
                },
            },
            "required": ["query"],
        },
    },
}


def rg_list_files(
    project_root=None,
    include_globs=None,
    exclude_globs=None,
    max_results=2000,
):
    try:
        root = _resolve_root(project_root)
        if not root:
            return json.dumps({"status": "error", "error": f"project_root not found: {project_root}"}, ensure_ascii=False)

        include_globs = _normalize_globs(include_globs)
        exclude_globs = _normalize_globs(exclude_globs)
        limit = _resolve_limit(max_results, default_value=2000, hard_max=20000)

        rg_path = shutil.which("rg")
        if rg_path:
            matches = []
            scanned_files = 0
            cmd = [rg_path, "--files", "--no-messages"]
            _append_rg_globs(cmd, include_globs, exclude_globs)
            cmd.append(root)

            def _on_line(raw_line):
                nonlocal scanned_files
                file_path = str(raw_line or "").strip()
                if not file_path:
                    return False
                scanned_files += 1
                if not os.path.isabs(file_path):
                    file_path = os.path.abspath(os.path.join(root, file_path))
                matches.append(
                    {
                        "file_path": file_path,
                        "relative_path": _safe_relpath(file_path, root),
                    }
                )
                return len(matches) >= limit

            meta = _run_rg_stream_lines(cmd, _on_line, timeout_sec=_RG_TIMEOUT_SEC)
            if not meta.get("ok"):
                return json.dumps(
                    {
                        "status": "error",
                        "engine": "rg",
                        "project_root": root,
                        "error": str(meta.get("error") or "failed to execute rg"),
                    },
                    ensure_ascii=False,
                )

            return_code = meta.get("return_code")
            if not meta.get("timed_out") and isinstance(return_code, int) and return_code not in (0, 1):
                return json.dumps(
                    {
                        "status": "error",
                        "engine": "rg",
                        "project_root": root,
                        "return_code": return_code,
                        "stderr": str(meta.get("stderr") or ""),
                    },
                    ensure_ascii=False,
                )

            return json.dumps(
                {
                    "status": "success",
                    "engine": "rg",
                    "project_root": root,
                    "scanned_files": scanned_files,
                    "files": matches,
                    "truncated": len(matches) >= limit or bool(meta.get("timed_out")),
                    "timed_out": bool(meta.get("timed_out")),
                },
                ensure_ascii=False,
            )

        matches = []
        scanned_files = 0
        for file_path in _iter_files_fallback(root):
            rel_path = _safe_relpath(file_path, root)
            if not _path_allowed(rel_path, include_globs, exclude_globs):
                continue
            scanned_files += 1
            matches.append(
                {
                    "file_path": file_path,
                    "relative_path": rel_path,
                }
            )
            if len(matches) >= limit:
                return json.dumps(
                    {
                        "status": "success",
                        "engine": "python",
                        "project_root": root,
                        "scanned_files": scanned_files,
                        "files": matches,
                        "truncated": True,
                    },
                    ensure_ascii=False,
                )

        return json.dumps(
            {
                "status": "success",
                "engine": "python",
                "project_root": root,
                "scanned_files": scanned_files,
                "files": matches,
                "truncated": False,
            },
            ensure_ascii=False,
        )
    except Exception as e:
        return json.dumps({"status": "exception", "error": str(e)}, ensure_ascii=False)


rg_list_files_declaration = {
    "type": "function",
    "function": {
        "name": "rg_list_files",
        "description": "List project files with ripgrep semantics (rg --files). Prefer this over shell dir/find.",
        "parameters": {
            "type": "object",
            "properties": {
                "project_root": {
                    "type": "string",
                    "description": "Project root directory. Defaults to current working directory.",
                },
                "include_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional include globs, e.g. ['*.ts', 'src/**'].",
                },
                "exclude_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional exclude globs, e.g. ['node_modules/**', 'dist/**'].",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum files to return (1-20000, default 2000).",
                    "default": 2000,
                },
            },
        },
    },
}
