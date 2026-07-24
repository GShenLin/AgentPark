"""Static capabilities and configuration contract for the Agent node."""

from nodes.agent_audio_schema import AUDIO_CONFIG_DEFAULTS, AUDIO_CONFIG_SCHEMA
from nodes.agent_generation_schema import GENERATION_CONFIG_DEFAULTS, GENERATION_CONFIG_SCHEMA
from nodes.agent_image_generation_schema import IMAGE_CONFIG_DEFAULTS, IMAGE_CONFIG_SCHEMA


AGENT_INPUT_CAPABILITIES = [
    "text", "resource:image", "resource:video", "resource:audio", "resource:doc",
    "resource:file", "resource:url", "structured", "meta",
]

AGENT_OUTPUT_CAPABILITIES = [
    "text", "resource:image", "resource:video", "resource:audio", "structured", "tool_call", "meta",
]

AGENT_CONFIG_DEFAULTS = {
    "provider_id": "",
    "instruction": "",
    "system_prompt": "",
    "collaboration_mode": "default",
    "plugins": [],
    "tools": [],
    "mcp_servers": [],
    "skills": [],
    "web_search": "disabled",
    "thinking": "disabled",
    "reasoning_effort": "high",
    "reasoning_summary": "",
    **IMAGE_CONFIG_DEFAULTS,
    **GENERATION_CONFIG_DEFAULTS,
    **AUDIO_CONFIG_DEFAULTS,
}

AGENT_CONFIG_SCHEMA = {
    "provider_id": {"type": "text", "label": "provider_id"},
    "instruction": {"type": "text", "label": "instruction"},
    "system_prompt": {"type": "text", "label": "system_prompt"},
    "collaboration_mode": {
        "type": "select",
        "label": "collaboration_mode",
        "options": [{"value": value, "label": value} for value in ("default", "plan")],
    },
    "plugins": {"type": "multiselect", "label": "plugins", "options": []},
    "tools": {"type": "multiselect", "label": "tools", "options": []},
    "mcp_servers": {"type": "multiselect", "label": "mcp_servers", "options": []},
    "skills": {"type": "multiselect", "label": "skills", "options": []},
    "web_search": {"type": "text", "label": "web_search"},
    "thinking": {"type": "text", "label": "thinking"},
    "reasoning_effort": {
        "type": "select",
        "label": "reasoning_effort",
        "options": [
            {"value": value, "label": value}
            for value in ("minimal", "low", "medium", "high", "xhigh")
        ],
    },
    "reasoning_summary": {
        "type": "select",
        "label": "reasoning_summary",
        "options": [
            {"value": value, "label": "provider default" if not value else value}
            for value in ("", "auto", "concise", "detailed", "disabled")
        ],
    },
    **IMAGE_CONFIG_SCHEMA,
    **GENERATION_CONFIG_SCHEMA,
    **AUDIO_CONFIG_SCHEMA,
}
