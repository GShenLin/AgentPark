from nodes.base_node import BaseNode
from src.clock_config import (
    CLOCK_INTERVAL_DAYS_KEY,
    CLOCK_INTERVAL_HOURS_KEY,
    CLOCK_INTERVAL_MINUTES_KEY,
    CLOCK_INTERVAL_SECONDS_KEY,
    build_clock_interval_fields,
)


class Node(BaseNode):
    name = "Clock"
    description = "Emit the configured text to downstream nodes at a fixed interval"

    _INTERVAL_DAYS_KEY = CLOCK_INTERVAL_DAYS_KEY
    _INTERVAL_HOURS_KEY = CLOCK_INTERVAL_HOURS_KEY
    _INTERVAL_MINUTES_KEY = CLOCK_INTERVAL_MINUTES_KEY
    _INTERVAL_SECONDS_KEY = CLOCK_INTERVAL_SECONDS_KEY
    _LOOP_KEY = "IsLoop"
    _LOOP_COUNT_KEY = "LoopCount"
    _OUTPUT_KEY = "OutputText"
    _RUNNING_KEY = "_clock_running"
    _NEXT_FIRE_AT_KEY = "_clock_next_fire_at"
    _REMAINING_KEY = "_clock_remaining_seconds"
    _TRIGGER_COUNT_KEY = "_clock_trigger_count"

    config_defaults = {
        _INTERVAL_DAYS_KEY: "0",
        _INTERVAL_HOURS_KEY: "0",
        _INTERVAL_MINUTES_KEY: "1",
        _INTERVAL_SECONDS_KEY: "0",
        _LOOP_KEY: True,
        _LOOP_COUNT_KEY: "0",
        _OUTPUT_KEY: "",
    }
    config_schema = {
        _INTERVAL_DAYS_KEY: {"type": "number", "label": "天"},
        _INTERVAL_HOURS_KEY: {"type": "number", "label": "时"},
        _INTERVAL_MINUTES_KEY: {"type": "number", "label": "分"},
        _INTERVAL_SECONDS_KEY: {"type": "number", "label": "秒"},
        _LOOP_KEY: {"type": "boolean", "label": "循环执行"},
        _LOOP_COUNT_KEY: {"type": "number", "label": "LoopCount(0=forever)"},
        _OUTPUT_KEY: {"type": "text", "label": "OutputText"},
    }
    internal_config_fields = {_RUNNING_KEY, _NEXT_FIRE_AT_KEY, _REMAINING_KEY, _TRIGGER_COUNT_KEY}

    def on_create(self, config: dict, context: dict | None = None) -> None:
        interval_fields = build_clock_interval_fields(config)
        super().on_create(config, context)
        if not isinstance(config, dict):
            return
        config.update(interval_fields)
        config.setdefault(self._RUNNING_KEY, False)
        config.setdefault(self._NEXT_FIRE_AT_KEY, None)
        config.setdefault(self._REMAINING_KEY, None)
        config.setdefault(self._TRIGGER_COUNT_KEY, 0)

    def getInputNum(self, context: dict | None = None) -> int:
        return 1

    def getOutputNum(self, context: dict | None = None) -> int:
        return 1

    def on_input(self, message: object, context: dict | None = None) -> dict:
        ctx = context or {}
        output_text = str(ctx.get(self._OUTPUT_KEY) or "")
        return self._text_output(output_text)
