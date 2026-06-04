from typing import Any

from nodes.base_node import BaseNode


class Node(BaseNode):
    name = "InputOutputTest"
    description = "用于测试多输入多输出路由的节点"
    config_defaults = {"prefix": "IOTEST"}
    config_schema = {"prefix": {"type": "text", "label": "prefix"}}

    def getInputNum(self, context: dict | None = None) -> int:
        return 3

    def getOutputNum(self, context: dict | None = None) -> int:
        return 4
