from nodes.base_node import BaseNode
from nodes.gui_agent_run import run_gui_agent


class Node(BaseNode):
    name = "GUI Agent"
    description = "Single-node GUI loop: capture, plan, execute, verify"
    gui_mode = "GUIAgent"
    supported_action_names = {
        "click",
        "left_double",
        "right_single",
        "drag",
        "type",
        "scroll",
        "wait",
        "finished",
        "long_press",
        "press_back",
        "press_home",
    }
    input_capabilities = ["text", "resource:image", "resource:url"]
    output_capabilities = ["text", "resource:image", "structured", "meta"]
    coordinate_scale = 1000
    min_screen_change_ratio = 0.0015
    default_wait_seconds = 2.0
    config_defaults = {
        "provider_id": "",
        "mode": gui_mode,
        "verify_mode": gui_mode,
        "instruction": "",
        "system_prompt": (
            "You are a GUI planning agent. Analyze the screenshot and output exactly:\n"
            "Thought: <short analysis>\n"
            "Action: <one action>\n"
            "Coordinates must use normalized 0-1000 values relative to screenshot width/height.\n"
            "Allowed actions: click, left_double, right_single, drag, type, scroll, wait, finished, long_press."
        ),
        "verify_prompt": (
            "Check if the GUI task is complete based on screenshot.\n"
            "Respond JSON only: {\"done\": true|false, \"reason\": \"...\"}."
        ),
        "verify_on_finish": "true",
        "dry_run": "false",
        "capture_region": "{}",
        "mock_actions": "[]",
        "planner_timeout_seconds": "120",
        "verify_timeout_seconds": "60",
    }
    config_schema = {
        "provider_id": {"type": "text", "label": "provider_id"},
        "instruction": {"type": "text", "label": "instruction (fallback if input empty)"},
        "system_prompt": {"type": "text", "label": "planner system_prompt"},
        "verify_prompt": {"type": "text", "label": "verify prompt"},
        "verify_on_finish": {"type": "text", "label": "verify on finished(true/false)"},
        "dry_run": {"type": "text", "label": "dry run(true/false)"},
        "capture_region": {"type": "json", "label": "capture region json"},
        "mock_actions": {"type": "json", "label": "mock actions array for offline test"},
        "planner_timeout_seconds": {"type": "text", "label": "planner timeout seconds"},
        "verify_timeout_seconds": {"type": "text", "label": "verify timeout seconds"},
    }

    def on_create(self, config: dict, context: dict | None = None) -> None:
        super().on_create(config, context)
        if not isinstance(config, dict):
            return
        for key in (
            "max_steps",
            "no_change_limit",
            "verifier_provider_id",
            "wait_seconds",
            "step_delay_seconds",
            "auto_scale_coords",
        ):
            config.pop(key, None)

    def on_input(self, message: object, context: dict | None = None) -> dict:
        return run_gui_agent(self, message, context)
