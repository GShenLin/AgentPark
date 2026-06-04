import os

from nodes.base_node import BaseNode
from src.web_backend.state_store import _read_json_dict, _write_json_dict


class Node(BaseNode):
    name = "Loop"
    description = "Repeat the loop branch for a configured number of iterations, then exit"

    _COUNT_KEY = "LoopCount"
    _REMAINING_KEY = "_loop_remaining"
    config_defaults = {_COUNT_KEY: "1"}
    config_schema = {_COUNT_KEY: {"type": "number", "label": "LoopCount"}}
    internal_config_fields = {_REMAINING_KEY}

    @classmethod
    def _parse_loop_count(cls, value: object) -> int:
        try:
            parsed = int(float(value))
        except Exception:
            parsed = 1
        return max(0, parsed)

    def _resolve_config_path(self, context: dict | None = None) -> str:
        memory_path = self._resolve_memory_path(context)
        if not memory_path:
            return ""
        return os.path.join(os.path.dirname(memory_path), "config.json")

    def _resolve_remaining(self, config: dict, total: int) -> int:
        if not isinstance(config, dict):
            return total
        raw = config.get(self._REMAINING_KEY)
        if raw is None:
            return total
        try:
            remaining = int(float(raw))
        except Exception:
            return total
        return min(max(0, remaining), total)

    def on_create(self, config: dict, context: dict | None = None) -> None:
        super().on_create(config, context)

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 2

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context if isinstance(context, dict) else {}
        config_path = self._resolve_config_path(ctx)
        config = _read_json_dict(config_path) if config_path else {}
        if not isinstance(config, dict):
            config = {}

        total = self._parse_loop_count(config.get(self._COUNT_KEY) or ctx.get(self._COUNT_KEY))
        remaining = self._resolve_remaining(config, total)
        payload = self._normalize_message(message, default_role="assistant")

        if remaining <= 0:
            config[self._REMAINING_KEY] = total
            if config_path:
                _write_json_dict(config_path, config)
            return {
                "display": f"loop end ({total})",
                "routes": [{"output_index": 1, "payload": payload}],
            }

        next_remaining = remaining - 1
        config[self._REMAINING_KEY] = next_remaining
        if config_path:
            _write_json_dict(config_path, config)
        return {
            "display": f"loop continue ({next_remaining}/{total})",
            "routes": [{"output_index": 0, "payload": payload}],
        }
