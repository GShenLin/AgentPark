from __future__ import annotations

"""Unattended tool-permission resolution for Claude node turns.

A Claude node turn has no terminal and no permission dialog, so a native
``can_use_tool`` control request has no way to be answered. The SDK raises
``canUseTool callback is not provided`` and the turn fails instead of running.
Full access (``bypassPermissions``) avoids the request entirely and is the node
default; the resolver below covers explicitly selected modes that can still
raise one.
"""

from typing import Any

from claude_agent_sdk import PermissionResultAllow
from claude_agent_sdk import ToolPermissionContext

# Modes where the CLI evaluates a tool call as "ask" and reports it to the host.
# `bypassPermissions` never asks, `dontAsk` denies without asking, and `plan`
# never executes a tool, so none of them need a callback.
PROMPTING_PERMISSION_MODES = frozenset({"default", "acceptEdits", "auto"})


def needs_permission_callback(permission_mode: str) -> bool:
    return str(permission_mode or "").strip() in PROMPTING_PERMISSION_MODES


async def allow_unattended_tool_use(
    tool_name: str,
    tool_input: dict[str, Any],
    context: ToolPermissionContext,
) -> PermissionResultAllow:
    # The node executes as the workspace owner; the mode selection is the
    # authorization decision, not an interactive prompt that cannot be shown.
    return PermissionResultAllow()


__all__ = ["PROMPTING_PERMISSION_MODES", "allow_unattended_tool_use", "needs_permission_callback"]
