import fnmatch
import json
import os
import queue
import re
import shutil
import subprocess
import threading
import time

from src.runtime_cancellation import CancellationRequested, cancel_source_from_agent, raise_if_cancel_requested


RG_LINE_RE = re.compile(r"^(.*?):(\d+):(.*)$")
RG_TIMEOUT_SEC = 15
RG_STOP_WAIT_SEC = 0.5

DEFAULT_SKIP_DIRS = {
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

project_file_stats_declaration = {
    "type": "function",
    "function": {
        "name": "project_file_stats",
        "description": (
            "Return structured project file counts and largest files while skipping generated/vendor folders. "
            "Use this instead of recursive shell line-count or inventory scans."
        ),
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
                    "description": "Optional include globs, e.g. ['*.py', 'src/**'].",
                },
                "exclude_globs": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional exclude globs, e.g. ['webui/dist/**'].",
                },
                "max_files": {
                    "type": "integer",
                    "description": "Maximum files to inspect (1-20000, default 20000).",
                    "default": 20000,
                },
                "top_n": {
                    "type": "integer",
                    "description": "Largest files to return (1-100, default 20).",
                    "default": 20,
                },
                "include_line_counts": {
                    "type": "boolean",
                    "description": "When true, count lines for returned largest files only.",
                    "default": False,
                },
            },
        },
    },
}


def rg_search_text(
    query,
    project_root=None,
    include_globs=None,
    exclude_globs=None,
    case_sensitive=False,
    fixed_strings=True,
    max_results=200,
    agent=None,
):
    try:
        if not isinstance(query, str) or not query.strip():
            return json.dumps({"status": "error", "error": "query is required"}, ensure_ascii=False)

        root = resolve_root(project_root)
        if not root:
            return json.dumps({"status": "error", "error": f"project_root not found: {project_root}"}, ensure_ascii=False)

        include_globs = normalize_globs(include_globs)
        exclude_globs = normalize_globs(exclude_globs)
        limit = resolve_limit(max_results, default_value=200, hard_max=5000)
        case_sensitive = bool(case_sensitive)
        fixed_strings = bool(fixed_strings)
        stripped_query = query.strip()

        rg_path = shutil.which("rg")
        cancel_source = cancel_source_from_agent(agent)
        if rg_path:
            return _search_with_rg(
                rg_path=rg_path,
                root=root,
                query=stripped_query,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                case_sensitive=case_sensitive,
                fixed_strings=fixed_strings,
                limit=limit,
                cancel_source=cancel_source,
            )

        return _search_with_python(
            root=root,
            query=stripped_query,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            case_sensitive=case_sensitive,
            fixed_strings=fixed_strings,
            limit=limit,
            cancel_source=cancel_source,
        )
    except CancellationRequested as e:
        return json.dumps({"status": "stopped", "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "exception", "error": str(e)}, ensure_ascii=False)


def rg_list_files(
    project_root=None,
    include_globs=None,
    exclude_globs=None,
    max_results=2000,
    agent=None,
):
    try:
        root = resolve_root(project_root)
        if not root:
            return json.dumps({"status": "error", "error": f"project_root not found: {project_root}"}, ensure_ascii=False)

        include_globs = normalize_globs(include_globs)
        exclude_globs = normalize_globs(exclude_globs)
        limit = resolve_limit(max_results, default_value=2000, hard_max=20000)

        rg_path = shutil.which("rg")
        cancel_source = cancel_source_from_agent(agent)
        if rg_path:
            return _list_files_with_rg(
                rg_path=rg_path,
                root=root,
                include_globs=include_globs,
                exclude_globs=exclude_globs,
                limit=limit,
                cancel_source=cancel_source,
            )

        return _list_files_with_python(
            root=root,
            include_globs=include_globs,
            exclude_globs=exclude_globs,
            limit=limit,
            cancel_source=cancel_source,
        )
    except CancellationRequested as e:
        return json.dumps({"status": "stopped", "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "exception", "error": str(e)}, ensure_ascii=False)


def project_file_stats(
    project_root=None,
    include_globs=None,
    exclude_globs=None,
    max_files=20000,
    top_n=20,
    include_line_counts=False,
    agent=None,
):
    try:
        root = resolve_root(project_root)
        if not root:
            return json.dumps({"status": "error", "error": f"project_root not found: {project_root}"}, ensure_ascii=False)

        include_globs = normalize_globs(include_globs)
        exclude_globs = normalize_globs(exclude_globs)
        file_limit = resolve_limit(max_files, default_value=20000, hard_max=20000)
        top_limit = resolve_limit(top_n, default_value=20, hard_max=100)
        cancel_source = cancel_source_from_agent(agent)

        scanned_files = 0
        total_bytes = 0
        skipped_errors = 0
        by_extension: dict[str, dict] = {}
        top_files: list[dict] = []

        for file_path in iter_files_fallback(root):
            raise_if_cancel_requested(cancel_source)
            rel_path = safe_relpath(file_path, root)
            if not path_allowed(rel_path, include_globs, exclude_globs):
                continue

            try:
                stat = os.stat(file_path)
            except OSError:
                skipped_errors += 1
                continue

            scanned_files += 1
            size_bytes = int(stat.st_size)
            total_bytes += size_bytes
            extension = file_extension(rel_path)
            extension_bucket = by_extension.setdefault(
                extension,
                {"files": 0, "bytes": 0},
            )
            extension_bucket["files"] += 1
            extension_bucket["bytes"] += size_bytes

            top_files.append(
                {
                    "file_path": file_path,
                    "relative_path": rel_path,
                    "extension": extension,
                    "size_bytes": size_bytes,
                }
            )
            top_files.sort(key=lambda item: item["size_bytes"], reverse=True)
            if len(top_files) > top_limit:
                top_files.pop()

            if scanned_files >= file_limit:
                break

        if include_line_counts:
            for item in top_files:
                raise_if_cancel_requested(cancel_source)
                item["line_count"] = count_file_lines(item["file_path"])

        return json.dumps(
            {
                "status": "success",
                "project_root": root,
                "scanned_files": scanned_files,
                "total_bytes": total_bytes,
                "by_extension": dict(sorted(by_extension.items())),
                "top_files_by_size": top_files,
                "truncated": scanned_files >= file_limit,
                "max_files": file_limit,
                "skipped_errors": skipped_errors,
                "line_counts_scope": "top_files_by_size" if include_line_counts else "not_requested",
                "skipped_dirs": sorted(DEFAULT_SKIP_DIRS),
            },
            ensure_ascii=False,
        )
    except CancellationRequested as e:
        return json.dumps({"status": "stopped", "error": str(e)}, ensure_ascii=False)
    except Exception as e:
        return json.dumps({"status": "exception", "error": str(e)}, ensure_ascii=False)


def resolve_root(project_root):
    root = project_root if isinstance(project_root, str) and project_root.strip() else os.getcwd()
    root = os.path.abspath(root)
    if not os.path.isdir(root):
        return None
    return root


def resolve_limit(raw_value, default_value, hard_max):
    try:
        value = int(raw_value)
    except Exception:
        value = default_value
    return max(1, min(value, hard_max))


def normalize_globs(raw_globs):
    if not isinstance(raw_globs, list):
        return []
    out = []
    seen = set()
    for item in raw_globs:
        value = str(item or "").strip()
        if not value or value in seen:
            continue
        seen.add(value)
        out.append(value)
    return out


def safe_relpath(path, root):
    try:
        return os.path.relpath(path, root)
    except Exception:
        return path


def normalize_rel_path(path):
    return str(path or "").replace("\\", "/")


def match_any_glob(rel_path, globs):
    if not globs:
        return False
    rel_norm = normalize_rel_path(rel_path)
    base = os.path.basename(rel_norm)
    for pattern in globs:
        if fnmatch.fnmatch(rel_norm, pattern) or fnmatch.fnmatch(base, pattern):
            return True
    return False


def path_allowed(rel_path, include_globs, exclude_globs):
    if include_globs and not match_any_glob(rel_path, include_globs):
        return False
    if exclude_globs and match_any_glob(rel_path, exclude_globs):
        return False
    return True


def iter_files_fallback(root):
    skip_dirs = {name.lower() for name in DEFAULT_SKIP_DIRS}
    for current_root, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d.lower() not in skip_dirs]
        for filename in files:
            yield os.path.join(current_root, filename)


def file_extension(rel_path):
    _, ext = os.path.splitext(str(rel_path or ""))
    return ext.lower() if ext else "[no extension]"


def count_file_lines(file_path):
    line_count = 0
    last_byte = b""
    with open(file_path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            line_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if last_byte and last_byte != b"\n":
        line_count += 1
    return line_count


def append_rg_globs(cmd, include_globs, exclude_globs):
    for pattern in include_globs:
        cmd.extend(["-g", pattern])
    for pattern in exclude_globs:
        cmd.extend(["-g", f"!{pattern}"])
    for directory in sorted(DEFAULT_SKIP_DIRS):
        cmd.extend(["-g", f"!{directory}/**"])


def terminate_process(proc):
    if proc is None or proc.poll() is not None:
        return
    try:
        proc.terminate()
        proc.wait(timeout=RG_STOP_WAIT_SEC)
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=RG_STOP_WAIT_SEC)
        except Exception:
            pass


def run_rg_stream_lines(cmd, on_line, timeout_sec, cancel_source=None):
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
        line_queue: queue.Queue[str | None] = queue.Queue()

        def _read_stdout() -> None:
            try:
                if proc.stdout:
                    for raw in proc.stdout:
                        line_queue.put(raw)
            finally:
                line_queue.put(None)

        threading.Thread(target=_read_stdout, daemon=True, name="rg-reader").start()
        while True:
            raise_if_cancel_requested(cancel_source)
            if timeout_sec and time.monotonic() >= deadline:
                timed_out = True
                break

            try:
                line = line_queue.get(timeout=0.05)
            except queue.Empty:
                continue
            if line is None:
                break

            had_output = True
            if on_line(line.rstrip("\r\n")):
                stopped_early = True
                break

            if proc.poll() is not None:
                break
    except CancellationRequested:
        stopped_early = True
        raise
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
            terminate_process(proc)

        if proc is not None:
            try:
                stderr_text = proc.stderr.read() if proc.stderr else ""
            except Exception:
                stderr_text = ""
            try:
                return_code = proc.wait(timeout=RG_STOP_WAIT_SEC)
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


def parse_rg_line(raw_line):
    if not isinstance(raw_line, str) or not raw_line:
        return None
    m = RG_LINE_RE.match(raw_line)
    if not m:
        return None
    file_path = m.group(1)
    try:
        line_number = int(m.group(2))
    except Exception:
        return None
    line_text = m.group(3)
    return file_path, line_number, line_text


def _search_with_rg(
    *,
    rg_path,
    root,
    query,
    include_globs,
    exclude_globs,
    case_sensitive,
    fixed_strings,
    limit,
    cancel_source=None,
):
    matches = []
    cmd = [rg_path, "-n", "--color", "never", "--no-messages", "--max-columns", "400", "--max-columns-preview"]
    if fixed_strings:
        cmd.append("-F")
    if not case_sensitive:
        cmd.append("-i")
    append_rg_globs(cmd, include_globs, exclude_globs)
    cmd.extend([query, root])

    def _on_line(raw_line):
        parsed = parse_rg_line(raw_line)
        if not parsed:
            return False
        file_path, line_number, line_text = parsed
        if not os.path.isabs(file_path):
            file_path = os.path.abspath(os.path.join(root, file_path))

        matches.append(
            {
                "file_path": file_path,
                "relative_path": safe_relpath(file_path, root),
                "line": line_number,
                "match": str(line_text or "").strip()[:400],
            }
        )
        return len(matches) >= limit

    meta = run_rg_stream_lines(cmd, _on_line, timeout_sec=RG_TIMEOUT_SEC, cancel_source=cancel_source)
    if not meta.get("ok"):
        return json.dumps(
            {
                "status": "error",
                "engine": "rg",
                "query": query,
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
                "query": query,
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
            "query": query,
            "project_root": root,
            "fixed_strings": fixed_strings,
            "case_sensitive": case_sensitive,
            "matches": matches,
            "truncated": len(matches) >= limit or bool(meta.get("timed_out")),
            "timed_out": bool(meta.get("timed_out")),
        },
        ensure_ascii=False,
    )


def _search_with_python(
    *,
    root,
    query,
    include_globs,
    exclude_globs,
    case_sensitive,
    fixed_strings,
    limit,
    cancel_source=None,
):
    flags = 0 if case_sensitive else re.IGNORECASE
    try:
        compiled = re.compile(re.escape(query) if fixed_strings else query, flags)
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
    for file_path in iter_files_fallback(root):
        raise_if_cancel_requested(cancel_source)
        rel_path = safe_relpath(file_path, root)
        if not path_allowed(rel_path, include_globs, exclude_globs):
            continue
        searched_files += 1
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as f:
                for line_no, line in enumerate(f, start=1):
                    raise_if_cancel_requested(cancel_source)
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
                            return _python_search_success(
                                root=root,
                                query=query,
                                fixed_strings=fixed_strings,
                                case_sensitive=case_sensitive,
                                searched_files=searched_files,
                                matches=matches,
                                truncated=True,
                            )
        except Exception:
            continue

    return _python_search_success(
        root=root,
        query=query,
        fixed_strings=fixed_strings,
        case_sensitive=case_sensitive,
        searched_files=searched_files,
        matches=matches,
        truncated=False,
    )


def _python_search_success(
    *,
    root,
    query,
    fixed_strings,
    case_sensitive,
    searched_files,
    matches,
    truncated,
):
    return json.dumps(
        {
            "status": "success",
            "engine": "python",
            "query": query,
            "project_root": root,
            "fixed_strings": fixed_strings,
            "case_sensitive": case_sensitive,
            "searched_files": searched_files,
            "matches": matches,
            "truncated": truncated,
        },
        ensure_ascii=False,
    )


def _list_files_with_rg(*, rg_path, root, include_globs, exclude_globs, limit, cancel_source=None):
    matches = []
    scanned_files = 0
    cmd = [rg_path, "--files", "--no-messages"]
    append_rg_globs(cmd, include_globs, exclude_globs)
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
                "relative_path": safe_relpath(file_path, root),
            }
        )
        return len(matches) >= limit

    meta = run_rg_stream_lines(cmd, _on_line, timeout_sec=RG_TIMEOUT_SEC, cancel_source=cancel_source)
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


def _list_files_with_python(*, root, include_globs, exclude_globs, limit, cancel_source=None):
    matches = []
    scanned_files = 0
    for file_path in iter_files_fallback(root):
        raise_if_cancel_requested(cancel_source)
        rel_path = safe_relpath(file_path, root)
        if not path_allowed(rel_path, include_globs, exclude_globs):
            continue
        scanned_files += 1
        matches.append(
            {
                "file_path": file_path,
                "relative_path": rel_path,
            }
        )
        if len(matches) >= limit:
            return _python_list_success(root=root, scanned_files=scanned_files, matches=matches, truncated=True)

    return _python_list_success(root=root, scanned_files=scanned_files, matches=matches, truncated=False)


def _python_list_success(*, root, scanned_files, matches, truncated):
    return json.dumps(
        {
            "status": "success",
            "engine": "python",
            "project_root": root,
            "scanned_files": scanned_files,
            "files": matches,
            "truncated": truncated,
        },
        ensure_ascii=False,
    )
