def truncate_text(text, max_chars):
    if text is None:
        return "", False, 0
    s = text if isinstance(text, str) else str(text)
    total = len(s)
    if not isinstance(max_chars, int) or max_chars <= 0 or total <= max_chars:
        return s, False, total
    marker = "\n...(truncated)...\n"
    tail_len = min(2000, max_chars // 3)
    head_len = max_chars - len(marker) - tail_len
    if head_len <= 0 or tail_len <= 0:
        return s[-max_chars:], True, total
    head = s[:head_len]
    tail = s[-tail_len:]
    return head + marker + tail, True, total


def decode_bytes(data, preferred_encoding):
    if not data:
        return ""
    if not isinstance(data, (bytes, bytearray)):
        try:
            data = bytes(data)
        except Exception:
            return str(data)

    tried = []
    for enc in ("utf-8", "gb18030", preferred_encoding):
        if not isinstance(enc, str) or not enc.strip():
            continue
        enc = enc.strip()
        if enc in tried:
            continue
        tried.append(enc)
        try:
            return data.decode(enc, errors="strict")
        except Exception:
            continue
    try:
        return data.decode(preferred_encoding or "utf-8", errors="replace")
    except Exception:
        return data.decode("utf-8", errors="replace")


def redact_sensitive_curl_args(cmd_parts):
    if not cmd_parts:
        return cmd_parts
    redacted = []
    redact_next = False
    for part in cmd_parts:
        if redact_next:
            redacted.append("REDACTED")
            redact_next = False
            continue
        lower = part.lower()
        if lower in ("-h", "--header"):
            redacted.append(part)
            redact_next = True
            continue
        if lower.startswith("authorization:") or lower.startswith("cookie:"):
            redacted.append("REDACTED")
            continue
        redacted.append(part)
    return redacted
