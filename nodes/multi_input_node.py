import os

from nodes.base_node import BaseNode
from src.message_protocol import envelope_text, normalize_envelope
from src.value_parsing import parse_int_value
from src.web_backend.state_store import _patch_node_config_persistent_fields, _read_json_dict


class Node(BaseNode):
    name = "MultiInput"
    description = "Wait until all input ports receive messages, then merge them in port order"

    _INPUT_COUNT_KEY = "InputCount"
    _BUFFER_KEY = "_multi_input_buffer"
    config_defaults = {_INPUT_COUNT_KEY: "2"}
    config_schema = {_INPUT_COUNT_KEY: {"type": "number", "label": "InputCount"}}
    internal_config_fields = {_BUFFER_KEY}

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
        return parse_int_value(ctx.get(self._INPUT_COUNT_KEY), default=2, minimum=1)

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        config_path = self._resolve_config_path(ctx)
        config = _read_json_dict(config_path) if config_path else {}
        if not isinstance(config, dict):
            config = {}

        effective_count = parse_int_value(
            config.get(self._INPUT_COUNT_KEY) or ctx.get(self._INPUT_COUNT_KEY),
            default=2,
            minimum=1,
        )
        slots = self._normalize_buffer(config, effective_count)

        input_index_raw = ctx.get("input_port_index")
        if input_index_raw is None:
            input_index_raw = ctx.get("input_index")
        input_index = parse_int_value(input_index_raw, default=0, minimum=0, maximum=max(0, effective_count - 1))

        slots[input_index] = normalize_envelope(message, default_role="user")

        ready = all(isinstance(item, dict) for item in slots)
        if not ready:
            config[self._BUFFER_KEY] = slots
            if config_path:
                _patch_node_config_persistent_fields(config_path, {self._BUFFER_KEY: slots})
            received = sum(1 for item in slots if isinstance(item, dict))
            return {
                "display": f"waiting {received}/{effective_count}",
                "routes": [],
                "suppress_output": True,
            }

        merged_text = "".join(envelope_text(item) for item in slots if isinstance(item, dict))
        config[self._BUFFER_KEY] = [None] * effective_count
        if config_path:
            _patch_node_config_persistent_fields(config_path, {self._BUFFER_KEY: config[self._BUFFER_KEY]})
        return self._text_output(merged_text)
