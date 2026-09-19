from __future__ import annotations

"""Parse the Seed textual tool-call dialect, without interpreting command text."""

import re
from dataclasses import dataclass

from .contracts import CodexProtocolError


OPEN = "<seed:tool_call>"
CLOSE = "</seed:tool_call>"
_FUNCTION = re.compile(r'<function name="([A-Za-z_][A-Za-z0-9_.-]*)">')
_PARAMETER = re.compile(
    r'<parameter name="([A-Za-z_][A-Za-z0-9_]*)"'
    r'(?: (string|number|integer|boolean|object|array|null)"| type="(string|number|integer|boolean|object|array|null)")?>'
)
_DISPLACED_TYPE = re.compile(r' (string|number|integer|boolean|object|array|null)">')
_CODE_OR_MARKER = re.compile(r'`+|~{3,}|<seed:tool_call>')


@dataclass(frozen=True)
class SeedParameter:
    name: str
    text: str
    type_hint: str = ""


@dataclass(frozen=True)
class SeedCall:
    name: str
    parameters: tuple[SeedParameter, ...]


def split_seed_calls(text: str) -> tuple[str, tuple[SeedCall, ...]]:
    """Only unquoted terminal Seed blocks are calls; Markdown code stays literal.

    Seed sometimes emits ``name="cmd" string">`` or ``name="cmd"> string">``.
    These are explicit dialect productions, not general malformed-XML repair.
    Parameter bodies are raw text: PowerShell '<', '&', quotes and backslashes
    must survive unchanged, so an XML parser/entity decoder is inappropriate.
    """
    start = _marker_outside_code(text)
    if start is None:
        return text, ()
    cursor = start
    calls: list[SeedCall] = []
    while cursor < len(text):
        cursor = _whitespace(text, cursor)
        if cursor == len(text):
            break
        if not text.startswith(OPEN, cursor):
            raise CodexProtocolError("Seed tool-call blocks must end the assistant text.")
        cursor += len(OPEN)
        block_calls = 0
        while True:
            cursor = _whitespace(text, cursor)
            if text.startswith(CLOSE, cursor):
                if not block_calls:
                    raise CodexProtocolError("Seed tool-call block contains no functions.")
                cursor += len(CLOSE)
                break
            match = _FUNCTION.match(text, cursor)
            if match is None:
                raise CodexProtocolError("Seed tool-call block has an incomplete or invalid function.")
            name = match[1]
            cursor = match.end()
            parameters: list[SeedParameter] = []
            names: set[str] = set()
            while True:
                cursor = _whitespace(text, cursor)
                if text.startswith("</function>", cursor):
                    cursor += len("</function>")
                    break
                parameter = _PARAMETER.match(text, cursor)
                if parameter is None:
                    raise CodexProtocolError(f"Seed function {name!r} has an incomplete or invalid parameter.")
                key = parameter[1]
                if key in names:
                    raise CodexProtocolError(f"Seed function {name!r} repeats parameter {key!r}.")
                names.add(key)
                hint = parameter[2] or parameter[3] or ""
                cursor = parameter.end()
                displaced = _DISPLACED_TYPE.match(text, cursor) if not hint else None
                if displaced is not None:
                    hint = displaced[1]
                    cursor = displaced.end()
                end = text.find("</parameter>", cursor)
                if end < 0:
                    raise CodexProtocolError(f"Seed function {name!r} has an unclosed parameter.")
                body = text[cursor:end]
                if any(tag in body for tag in ("<function ", "</function>", "<parameter ", OPEN, CLOSE)):
                    raise CodexProtocolError(f"Seed parameter {key!r} contains nested protocol tags.")
                parameters.append(SeedParameter(key, body, hint))
                cursor = end + len("</parameter>")
            calls.append(SeedCall(name, tuple(parameters)))
            block_calls += 1
    return text[:start], tuple(calls)


def _whitespace(text: str, cursor: int) -> int:
    while cursor < len(text) and text[cursor].isspace():
        cursor += 1
    return cursor


def _marker_outside_code(text: str) -> int | None:
    cursor = 0
    while match := _CODE_OR_MARKER.search(text, cursor):
        token = match[0]
        cursor = match.end()
        if match.start() and text[match.start() - 1] == "\\":
            continue
        if token == OPEN:
            return match.start()
        closing = text.find(token, cursor)
        if closing < 0:
            return None
        cursor = closing + len(token)
    return None
