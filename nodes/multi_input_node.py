import os

from nodes.base_node import BaseNode
from src.web_backend.state_store import _read_json_dict, _write_json_dict


class Node(BaseNode):
    name = "MultiInput"
    description = "Wait until all input ports receive messages, then merge them in port order"

    _INPUT_COUNT_KEY = "InputCount"
    _BUFFER_KEY = "_multi_input_buffer"
    config_defaults = {_INPUT_COUNT_KEY: "2"}
    config_schema = {_INPUT_COUNT_KEY: {"type": "number", "label": "InputCount"}}
    internal_config_fields = {_BUFFER_KEY}

    @classmethod
    def _parse_input_count(cls, value: object) -> int:
        try:
            parsed = int(float(value))
        except Exception:
            parsed = 2
        return max(1, parsed)

    def _resolve_config_path(self, context: dict | None = None) -> str:
        memory_path = self._resolve_memory_path(context)
        if not memory_path:
            return ""
        return os.path.join(os.path.dirname(memory_path), "config.json")

    def _normalize_buffer(self, config: dict, input_count: int) -> list[dict | None]:
        existing = config.get(self._BUFFER_KEY)
        slots = existing if isinstance(existing, list) else []
        normalized: list[dict | None] = []
        for index in range(input_count):
            item = slots[index] if index < len(slots) else None
            normalized.append(item if isinstance(item, dict) else None)
        config[self._BUFFER_KEY] = normalized
        return normalized

    def on_create(self, config: dict, context: dict | None = None) -> None:
        super().on_create(config, context)
        if not isinstance(config, dict):
            return
        self._normalize_buffer(config, self.getInputNum(config))

    def getInputNum(self, context: dict | None = None) -> int:
        ctx = context if isinstance(context, dict) else {}
        return self._parse_input_count(ctx.get(self._INPUT_COUNT_KEY))

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        config_path = self._resolve_config_path(ctx)
        config = _read_json_dict(config_path) if config_path else {}
        if not isinstance(config, dict):
            config = {}

        effective_count = self._parse_input_count(config.get(self._INPUT_COUNT_KEY) or ctx.get(self._INPUT_COUNT_KEY))
        slots = self._normalize_buffer(config, effective_count)

        input_index_raw = ctx.get("input_port_index")
        if input_index_raw is None:
            input_index_raw = ctx.get("input_index")
        try:
            input_index = int(float(input_index_raw))
        except Exception:
            input_index = 0
        if input_index < 0 or input_index >= effective_count:
            input_index = 0

        slots[input_index] = self._normalize_message(message, default_role="user")

        ready = all(isinstance(item, dict) for item in slots)
        if not ready:
            config[self._BUFFER_KEY] = slots
            if config_path:
                _write_json_dict(config_path, config)
            received = sum(1 for item in slots if isinstance(item, dict))
            return {
                "display": f"waiting {received}/{effective_count}",
                "routes": [],
                "suppress_output": True,
            }

        merged_text = "".join(self._message_text(item) for item in slots if isinstance(item, dict))
        config[self._BUFFER_KEY] = [None] * effective_count
        if config_path:
            _write_json_dict(config_path, config)
        return self._text_output(merged_text)
