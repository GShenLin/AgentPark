"""Read literal fields from WeChat's cgiDataNew; never evaluate JavaScript.

Unneeded expressions remain opaque strings. Only explicitly requested string
fields and containers are interpreted, so page code cannot execute in Python.
"""
import re


class ArticleParseError(ValueError):
    pass


def _quoted_end(source: str, start: int) -> int:
    quote = source[start]
    i = start + 1
    while i < len(source):
        if source[i] == "\\":
            i += 2
        elif source[i] == quote:
            return i + 1
        else:
            i += 1
    raise ArticleParseError("Unterminated JavaScript string")


def _boundary(source: str, start: int, separators: str) -> int:
    stack = []
    i = start
    while i < len(source):
        char = source[i]
        if char in "\"'":
            i = _quoted_end(source, i)
            continue
        if source.startswith("//", i):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end + 1
            continue
        if source.startswith("/*", i):
            end = source.find("*/", i + 2)
            if end < 0:
                raise ArticleParseError("Unterminated JavaScript comment")
            i = end + 2
            continue
        if not stack and char in separators:
            return i
        if char in "{[":
            stack.append({"{": "}", "[": "]"}[char])
        elif char in "}]":
            if not stack or stack.pop() != char:
                raise ArticleParseError("Unbalanced embedded article data")
            if not stack and not separators:
                return i + 1
        i += 1
    if stack:
        raise ArticleParseError("Incomplete embedded article data")
    return i


def string_literal(raw: str) -> str:
    raw = raw.strip()
    if not raw or raw[0] not in "\"'" or _quoted_end(raw, 0) != len(raw):
        raise ArticleParseError("Expected a literal string in article data")
    text = raw[1:-1]
    result = []
    escapes = {"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f",
               "v": "\v", "0": "\0", "\\": "\\", "'": "'", '"': '"', "/": "/"}
    i = 0
    while i < len(text):
        if text[i] != "\\":
            result.append(text[i])
            i += 1
            continue
        i += 1
        char = text[i]
        if char in {"x", "u"}:
            size = 2 if char == "x" else 4
            digits = text[i + 1:i + 1 + size]
            if len(digits) != size or not re.fullmatch(r"[0-9a-fA-F]+", digits):
                raise ArticleParseError("Invalid escaped character in article data")
            result.append(chr(int(digits, 16)))
            i += size + 1
        elif char in escapes:
            result.append(escapes[char])
            i += 1
        else:
            raise ArticleParseError(f"Unsupported JavaScript escape: {char}")
    try:
        return "".join(result).encode("utf-16", "surrogatepass").decode("utf-16")
    except UnicodeError as exc:
        raise ArticleParseError("Invalid Unicode in article data") from exc


def members(raw: str) -> dict[str, str]:
    if not raw.startswith("{") or not raw.endswith("}"):
        raise ArticleParseError("Expected an article data object")
    fields = {}
    for item in elements("[" + raw[1:-1] + "]"):
        colon = _boundary(item, 0, ":")
        key = item[:colon].strip()
        if key.startswith(("'", '"')):
            key = string_literal(key)
        if not re.fullmatch(r"[A-Za-z_$][A-Za-z0-9_$]*", key) or colon == len(item):
            raise ArticleParseError("Invalid article data property")
        if key in fields:
            raise ArticleParseError(f"Duplicate article data property: {key}")
        fields[key] = item[colon + 1:].strip()
    return fields


def elements(raw: str) -> list[str]:
    if not raw.startswith("[") or not raw.endswith("]"):
        raise ArticleParseError("Expected an article data array")
    inner = raw[1:-1]
    items = []
    start = 0
    while start < len(inner):
        end = _boundary(inner, start, ",")
        item = inner[start:end].strip()
        if item:
            items.append(item)
        start = end + 1
    return items


def article_data(scripts: list[str]) -> dict[str, str] | None:
    for script in scripts:
        match = re.search(r"\bwindow\.cgiDataNew\s*=\s*(?=\{)", script)
        if match:
            start = match.end()
            return members(script[start:_boundary(script, start, "")])
    return None
