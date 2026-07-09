import os

from nodes.base_node import BaseNode
from src.message_protocol import envelope_text


class Node(BaseNode):
    name = "SaveFile"
    description = "将输入内容保存到文件"
    config_defaults = {"FilePath": "", "FileName": ""}
    config_schema = {
        "FilePath": {"type": "text", "label": "文件路径"},
        "FileName": {"type": "text", "label": "文件名(可空)"},
    }

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def _resolve_output_file_name(self, file_name: str) -> str:
        safe_name = str(file_name or "").strip()
        if not safe_name:
            return "output.md"
        _, ext = os.path.splitext(safe_name)
        if ext:
            return safe_name
        return f"{safe_name}.md"

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        base_dir = str(ctx.get("FilePath") or "").strip()
        file_name = str(ctx.get("FileName") or "").strip()
        content = envelope_text(message)

        if not base_dir:
            raise ValueError("FilePath is required")

        if not file_name:
            head = content[:6].strip()
            file_name = head if head else "output"
        file_name = self._resolve_output_file_name(file_name)

        os.makedirs(base_dir, exist_ok=True)
        file_path = os.path.join(base_dir, file_name)

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)

        return self._text_output(content)
