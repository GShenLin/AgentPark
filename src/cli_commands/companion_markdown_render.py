from __future__ import annotations

import re

from src.cli_commands.companion_style import BOLD, CYAN, DIM, GREEN, YELLOW, style


INLINE_CODE_PATTERN = re.compile(r"`([^`\n]+)`")
STRONG_PATTERN = re.compile(r"\*\*([^*\n]+)\*\*")


def render_markdown_lines(text: object, *, indent: str = "") -> list[str]:
    lines: list[str] = []
    in_code_block = False
    code_language = ""
    for raw_line in str(text or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw_line.rstrip()
        stripped = line.strip()
        if stripped.startswith("```"):
            if in_code_block:
                lines.append(indent + style("  " + "-" * 24, DIM))
                in_code_block = False
                code_language = ""
            else:
                code_language = stripped[3:].strip()
                title = f" code {code_language} " if code_language else " code "
                lines.append(indent + style(title, YELLOW, BOLD))
                in_code_block = True
            continue
        if in_code_block:
            lines.append(indent + style("  " + line, YELLOW))
            continue
        lines.append(indent + _render_markdown_line(line))
    return lines or [indent]


def _render_markdown_line(line: str) -> str:
    stripped = line.strip()
    if not stripped:
        return ""
    heading = re.match(r"^(#{1,6})\s+(.+)$", stripped)
    if heading:
        level = len(heading.group(1))
        marker = ">" if level == 1 else "-" * min(level, 3)
        return style(f"{marker} {heading.group(2).strip()}", CYAN, BOLD)
    quote = re.match(r"^>\s?(.*)$", stripped)
    if quote:
        return style("| " + quote.group(1), DIM)
    bullet = re.match(r"^([-*+])\s+(.+)$", stripped)
    if bullet:
        return "- " + _render_inline(bullet.group(2))
    numbered = re.match(r"^(\d+)\.\s+(.+)$", stripped)
    if numbered:
        return f"{numbered.group(1)}. " + _render_inline(numbered.group(2))
    return _render_inline(line)


def _render_inline(text: str) -> str:
    rendered = INLINE_CODE_PATTERN.sub(lambda match: style(match.group(1), YELLOW), text)
    rendered = STRONG_PATTERN.sub(lambda match: style(match.group(1), BOLD, GREEN), rendered)
    return rendered


__all__ = ["render_markdown_lines"]
