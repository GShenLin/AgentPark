import json
import os
import re


DATE_DIR_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _truncate_line(text, max_chars):
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not isinstance(max_chars, int) or max_chars <= 0 or len(s) <= max_chars:
        return s
    if max_chars <= 3:
        return s[:max_chars]
    return s[: max_chars - 3] + "..."


def _agent_memory_path(agent):
    if agent is None:
        return ""
    try:
        mem_path = agent.getMemoryPath() if hasattr(agent, "getMemoryPath") else None
        return str(mem_path or "").strip()
    except Exception:
        return ""


def _default_memory_search_files(memory_path):
    path = str(memory_path or "").strip()
    if not path:
        return []

    files = []
    if os.path.isfile(path):
        files.append(path)

    node_dir = os.path.dirname(path)
    archive_dir = os.path.join(node_dir, "archive") if node_dir else ""
    if not os.path.isdir(archive_dir):
        return files

    date_dirs = [
        os.path.join(archive_dir, name)
        for name in os.listdir(archive_dir)
        if DATE_DIR_RE.match(name) and os.path.isdir(os.path.join(archive_dir, name))
    ]
    date_dirs.sort()

    for date_dir in date_dirs:
        for filename in ("legacy.memory.md", "memory.md"):
            candidate = os.path.join(date_dir, filename)
            if os.path.isfile(candidate):
                files.append(candidate)
    return files


def _coerce_positive_int(value, default):
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _line_matches(line, query, matcher, case_sensitive):
    if matcher is not None:
        return matcher.search(line) is not None
    if case_sensitive:
        return query in line
    return query.lower() in line.lower()


def search_memory(
    query,
    file_path=None,
    max_matches=20,
    case_sensitive=False,
    use_regex=False,
    max_line_chars=400,
    max_output_chars=12000,
    agent=None,
):
    q = query if isinstance(query, str) else str(query or "")
    q = q.strip()
    if not q:
        return json.dumps({"ok": False, "error": "query is required"}, ensure_ascii=False)

    path = ""
    archive_search = False
    if isinstance(file_path, str) and file_path.strip():
        path = file_path.strip()
        paths = [path]
    else:
        if agent is None:
            return json.dumps({"ok": False, "error": "agent context is missing"}, ensure_ascii=False)
        path = _agent_memory_path(agent)
        if not path:
            return json.dumps({"ok": False, "error": "agent memory path not available"}, ensure_ascii=False)
        paths = _default_memory_search_files(path)
        archive_search = True

    max_matches = _coerce_positive_int(max_matches, 20)
    max_line_chars = _coerce_positive_int(max_line_chars, 400)
    max_output_chars = _coerce_positive_int(max_output_chars, 12000)

    if not paths:
        return json.dumps(
            {
                "ok": False,
                "error": "memory file not found",
                "path": path,
                "archive_search": archive_search,
            },
            ensure_ascii=False,
        )
    missing = [item for item in paths if not os.path.exists(item)]
    if missing:
        return json.dumps(
            {"ok": False, "error": "memory file not found", "path": missing[0]},
            ensure_ascii=False,
        )

    flags = 0
    if not case_sensitive:
        flags |= re.IGNORECASE

    matcher = None
    if use_regex:
        try:
            matcher = re.compile(q, flags=flags)
        except Exception as e:
            return json.dumps({"ok": False, "error": f"invalid regex: {e}"}, ensure_ascii=False)

    matches = []
    total_matches = 0
    scanned_lines = 0
    scanned_files = 0

    try:
        for current_path in paths:
            scanned_files += 1
            with open(current_path, "r", encoding="utf-8", errors="replace") as f:
                for line_no, line in enumerate(f, start=1):
                    scanned_lines += 1
                    if not _line_matches(line, q, matcher, case_sensitive):
                        continue

                    total_matches += 1
                    if len(matches) < max_matches:
                        matches.append(
                            {
                                "file": current_path,
                                "line": line_no,
                                "text": _truncate_line(line.rstrip("\n\r"), max_line_chars),
                            }
                        )
    except Exception as e:
        return json.dumps(
            {"ok": False, "error": f"failed to read memory file: {e}", "path": path},
            ensure_ascii=False,
        )

    payload = {
        "ok": True,
        "path": path,
        "query": q,
        "use_regex": bool(use_regex),
        "case_sensitive": bool(case_sensitive),
        "archive_search": archive_search,
        "paths": paths,
        "scanned_files": scanned_files,
        "scanned_lines": scanned_lines,
        "total_matches": total_matches,
        "matches": matches,
        "truncated": total_matches > len(matches),
    }
    text = json.dumps(payload, ensure_ascii=False)
    if max_output_chars > 0 and len(text) > max_output_chars:
        payload["matches"] = payload["matches"][: max(1, min(len(payload["matches"]), 5))]
        payload["truncated"] = True
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > max_output_chars:
            text = text[: max_output_chars - 3] + "..."
    return text


search_memory_declaration = {
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": "Search active and archived agent memory markdown files for a query string or regex.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "file_path": {"type": "string"},
                "max_matches": {"type": "integer", "default": 20},
                "case_sensitive": {"type": "boolean", "default": False},
                "use_regex": {"type": "boolean", "default": False},
                "max_line_chars": {"type": "integer", "default": 400},
                "max_output_chars": {"type": "integer", "default": 12000},
            },
            "required": ["query"],
        },
    },
}
