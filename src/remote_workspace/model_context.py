"""Replace stale workspace instructions in each provider's next model request."""
from src.providers.agent_environment_context import (
    build_agent_environment_context, format_agent_environment_context, is_agent_environment_context_text,
)
from src.providers.agent_project_instructions import (
    build_agent_project_instructions_context, format_agent_project_instructions_context,
    is_agent_project_instructions_text, PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE,
    PROJECT_INSTRUCTIONS_REMOVAL_NOTICE,
)
from src.providers.agent_runtime_context import get_agent_runtime_context


PREFIX = "<execution_workspace_update>"


def _workspace_text(value):
    return isinstance(value, str) and (
        value.startswith(PREFIX) or is_agent_environment_context_text(value)
        or is_agent_project_instructions_text(value)
    )


def refresh_execution_messages(agent, messages, *, responses=False):
    context = get_agent_runtime_context(agent)
    if not context.execution_workspace:
        return list(messages)
    environment = format_agent_environment_context(build_agent_environment_context(agent))
    instructions = build_agent_project_instructions_context(agent)
    notice = (PROJECT_INSTRUCTIONS_REPLACEMENT_NOTICE if instructions.get("text")
              else PROJECT_INSTRUCTIONS_REMOVAL_NOTICE)
    texts = [
        PREFIX + "\nCurrent execution workspace; replaces prior device, shell, directory and project context."
        "\n</execution_workspace_update>",
        environment, format_agent_project_instructions_context(instructions, notice=notice),
    ]
    output = []
    for message in messages:
        if not isinstance(message, dict) or message.get("role") not in {"user", "system", "developer"}:
            output.append(message)
            continue
        content = message.get("content")
        if _workspace_text(content):
            continue
        if isinstance(content, list):
            parts = [part for part in content if not (
                isinstance(part, dict) and _workspace_text(part.get("text"))
            )]
            if content and not parts:
                continue
            message = {**message, "content": parts}
        output.append(message)
    prefix = []
    for text in texts:
        item = {"role": "user", "content": text}
        if responses:
            item = {"type": "message", "role": "user",
                    "content": [{"type": "input_text", "text": text}]}
        prefix.append(item)
    return [*prefix, *output]
