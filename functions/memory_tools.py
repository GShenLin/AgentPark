import json
import os
import re


def _truncate_line(text, max_chars):
    if text is None:
        return ""
    s = text if isinstance(text, str) else str(text)
    if not isinstance(max_chars, int) or max_chars <= 0 or len(s) <= max_chars:
        return s
    return s[: max_chars - 1] + "…"


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
    if isinstance(file_path, str) and file_path.strip():
        path = file_path.strip()
    else:
        if agent is None:
            return json.dumps({"ok": False, "error": "agent context is missing"}, ensure_ascii=False)
        try:
            mem_path = agent.getMemoryPath() if hasattr(agent, "getMemoryPath") else None
            path = str(mem_path or "").strip()
        except Exception:
            path = ""
        if not path:
            return json.dumps({"ok": False, "error": "agent memory path not available"}, ensure_ascii=False)

    try:
        max_matches = int(max_matches)
    except Exception:
        max_matches = 20
    if max_matches <= 0:
        max_matches = 20

    try:
        max_line_chars = int(max_line_chars)
    except Exception:
        max_line_chars = 400

    if not os.path.exists(path):
        return json.dumps(
            {"ok": False, "error": "memory file not found", "path": path},
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

    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, line in enumerate(f, start=1):
                scanned_lines += 1
                hay = line
                found = False
                if matcher is not None:
                    found = matcher.search(hay) is not None
                else:
                    if case_sensitive:
                        found = q in hay
                    else:
                        found = q.lower() in hay.lower()

                if not found:
                    continue

                total_matches += 1
                if len(matches) < max_matches:
                    matches.append(
                        {
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
        "scanned_lines": scanned_lines,
        "total_matches": total_matches,
        "matches": matches,
        "truncated": total_matches > len(matches),
    }
    text = json.dumps(payload, ensure_ascii=False)
    if isinstance(max_output_chars, int) and max_output_chars > 0 and len(text) > max_output_chars:
        payload["matches"] = payload["matches"][: max(1, min(len(payload["matches"]), 5))]
        payload["truncated"] = True
        text = json.dumps(payload, ensure_ascii=False)
        if len(text) > max_output_chars:
            text = text[: max_output_chars - 1] + "…"
    return text


search_memory_declaration = {
    "type": "function",
    "function": {
        "name": "search_memory",
        "description": "Search an agent memory markdown file for a query string or regex.",
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
