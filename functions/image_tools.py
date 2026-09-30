import json

from src.providers.agent_environment_context import resolve_agent_relative_path
from src.runtime_cancellation import cancel_source_from_agent, raise_if_cancel_requested
from src.tool.local_image import prepare_local_image


def view_image(path: str, detail: str = "high", agent=None) -> str:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("view_image.path must be a non-empty local filesystem path")
    cancel_source = cancel_source_from_agent(agent)
    raise_if_cancel_requested(cancel_source)
    result = prepare_local_image(resolve_agent_relative_path(path, agent=agent), detail)
    raise_if_cancel_requested(cancel_source)
    return json.dumps(result, ensure_ascii=False)


view_image_declaration = {
    "type": "function",
    "function": {
        "name": "view_image",
        "description": (
            "View a local image file when visual inspection is needed. Returns image content to the model. "
            "After reading Markdown, use this tool to view referenced images; resolve relative image links "
            "against the document directory. Do not use read_file or shell text output to inspect image pixels."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local image path; relative paths use the working directory."},
                "detail": {"type": "string", "enum": ["high", "original"],
                           "description": "Defaults to high (2048px / 2500 patches); original uses the model's larger 6000px / 10000 patch budget."},
            },
            "required": ["path"],
            "additionalProperties": False,
        },
    },
}
