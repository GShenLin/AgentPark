from __future__ import annotations

from difflib import SequenceMatcher


def build_file_change_hunks(before_text: str, after_text: str, *, context_lines: int = 5) -> list[dict]:
    before_lines = str(before_text or "").splitlines()
    after_lines = str(after_text or "").splitlines()
    context = max(0, int(context_lines))
    matcher = SequenceMatcher(a=before_lines, b=after_lines, autojunk=False)
    hunks: list[dict] = []
    for group in matcher.get_grouped_opcodes(n=context):
        rows: list[dict] = []
        for tag, before_start, before_end, after_start, after_end in group:
            if tag == "equal":
                for offset, text in enumerate(before_lines[before_start:before_end]):
                    rows.append(
                        {
                            "kind": "context",
                            "before_line": before_start + offset + 1,
                            "after_line": after_start + offset + 1,
                            "before_text": text,
                            "after_text": text,
                        }
                    )
                continue
            removed = before_lines[before_start:before_end]
            added = after_lines[after_start:after_end]
            for offset in range(max(len(removed), len(added))):
                row = {"kind": "change"}
                if offset < len(removed):
                    row["before_line"] = before_start + offset + 1
                    row["before_text"] = removed[offset]
                if offset < len(added):
                    row["after_line"] = after_start + offset + 1
                    row["after_text"] = added[offset]
                rows.append(row)
        if rows:
            hunks.append(
                {
                    "before_start": next((row["before_line"] for row in rows if "before_line" in row), None),
                    "after_start": next((row["after_line"] for row in rows if "after_line" in row), None),
                    "context_lines": context,
                    "rows": rows,
                }
            )
    return hunks


__all__ = ["build_file_change_hunks"]
