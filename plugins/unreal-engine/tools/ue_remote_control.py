def ue_remote_control(command, agent=None):
    raise RuntimeError(
        "ue_remote_control requires a paired AgentPark Remote node that advertises the ue_remote_control capability."
    )


ue_remote_control_declaration = {
    "type": "function",
    "function": {
        "name": "ue_remote_control",
        "description": (
            "Execute an unrestricted Unreal Engine console command on the paired Unreal runtime/editor node. "
            "The command is passed directly to Unreal Engine's GEngine->Exec on the active Game or PIE world, "
            "so use Unreal console syntax rather than PowerShell syntax. This includes console variables and "
            "commands such as 'stat fps', 'r.ScreenPercentage 50', 'show collision', 'open MapName', debug "
            "commands, travel commands, and process commands such as 'quit'. The command may change game state, "
            "load maps, write engine output, or terminate the Unreal process. Call the tool again for each "
            "command. The result reports whether Unreal handled the command, the selected world/map, and any "
            "text written to Unreal's command output device; some commands only write to the normal UE log and "
            "therefore can return an empty output string even when handled."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": (
                        "The exact Unreal Engine console command to execute, for example 'stat fps', "
                        "'r.VSync 0', 'open L_TestMap', or 'quit'."
                    ),
                }
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}


ue_remote_control.tool_timeout_seconds = 3600


__all__ = ["ue_remote_control", "ue_remote_control_declaration"]
