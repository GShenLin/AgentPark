def cancer_control(
    action="observe",
    actor=None,
    x=None,
    y=None,
    z=None,
    pitch=None,
    yaw=None,
    roll=None,
    radius=None,
    limit=None,
    name_filter=None,
    forward=None,
    right=None,
    force=None,
    sweep=None,
    key=None,
    event=None,
    amount=None,
    duration=None,
    stop_distance=None,
    count=None,
    interval=None,
    require_lock=None,
    command=None,
    filter=None,
    name=None,
    value=None,
    agent=None,
):
    raise RuntimeError(
        "cancer_control requires a paired AgentPark Remote node that advertises the cancer_control capability."
    )


cancer_control_declaration = {
    "type": "function",
    "function": {
        "name": "cancer_control",
        "description": (
            "Observe and control the paired Cancer-based Unreal game through the game-specific CancerControl "
            "surface implemented inside AgentParkRemote. This is separate from ue_remote_control: prefer it for "
            "structured player/world inspection, nearby Actor queries, camera aiming, movement, teleportation, "
            "lock/combat-state inspection, target-aware movement and attacks, input simulation, Cancer GM commands, "
            "and Cancer DebugConsole variables. Results are JSON strings. "
            "Use action='help' to list actions, action='observe' after actions to verify state, and avoid arbitrary "
            "console_command when a typed action is available."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "help",
                        "observe",
                        "status",
                        "list_actors",
                        "inspect_actor",
                        "look_at",
                        "set_control_rotation",
                        "teleport",
                        "move_input",
                        "jump",
                        "input_key",
                        "hold_key",
                        "combat_snapshot",
                        "nearest_enemies",
                        "lock_target",
                        "unlock_target",
                        "move_to_actor",
                        "attack_actor",
                        "gm_command",
                        "list_gm_commands",
                        "list_debug",
                        "get_debug_value",
                        "set_debug_value",
                        "console_command",
                    ],
                    "description": "CancerControl operation to perform. Defaults to observe.",
                },
                "actor": {
                    "type": "string",
                    "description": "Actor name or full object path. move_to_actor and attack_actor use the current lock target when omitted.",
                },
                "x": {"type": "number", "description": "World-space X for look_at or teleport."},
                "y": {"type": "number", "description": "World-space Y for look_at or teleport."},
                "z": {"type": "number", "description": "World-space Z for look_at or teleport."},
                "pitch": {"type": "number", "description": "Control rotation pitch in degrees."},
                "yaw": {"type": "number", "description": "Control rotation yaw in degrees."},
                "roll": {"type": "number", "description": "Control rotation roll in degrees."},
                "radius": {
                    "type": "number",
                    "description": "list_actors search radius in Unreal centimeters; default 3000.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum list_actors or list_debug entries to return.",
                },
                "name_filter": {
                    "type": "string",
                    "description": "Optional Actor name or class substring for list_actors.",
                },
                "forward": {
                    "type": "number",
                    "description": "Forward movement input scale for one game-thread dispatch.",
                },
                "right": {
                    "type": "number",
                    "description": "Right movement input scale for one game-thread dispatch.",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force movement input even when movement input is normally ignored.",
                },
                "sweep": {
                    "type": "boolean",
                    "description": "Sweep for collision during teleport; defaults to true.",
                },
                "key": {
                    "type": "string",
                    "description": "Unreal input key name, such as SpaceBar, LeftMouseButton, W, or Gamepad_FaceButton_Bottom.",
                },
                "event": {
                    "type": "string",
                    "enum": ["press", "release", "repeat", "axis"],
                    "description": "Input event kind for input_key; defaults to press.",
                },
                "amount": {
                    "type": "number",
                    "description": "Input amount for input_key/hold_key/move_to_actor; defaults to 1.",
                },
                "duration": {
                    "type": "number",
                    "description": "Hold or movement duration in seconds; clamped to 0.01-10.",
                },
                "stop_distance": {
                    "type": "number",
                    "description": "Desired distance from the target for move_to_actor, in Unreal centimeters; default 180.",
                },
                "count": {
                    "type": "integer",
                    "description": "Number of attacks to schedule for attack_actor; clamped to 1-20.",
                },
                "interval": {
                    "type": "number",
                    "description": "Seconds between scheduled attacks for attack_actor; clamped to 0.05-2.",
                },
                "require_lock": {
                    "type": "boolean",
                    "description": "Require actor to remain the current lock target for attack_actor; defaults to true.",
                },
                "command": {
                    "type": "string",
                    "description": "Full command line for gm_command or console_command.",
                },
                "filter": {
                    "type": "string",
                    "description": "Name, display-name, or group substring for list_debug.",
                },
                "name": {
                    "type": "string",
                    "description": "Cancer debug variable or command name for get_debug_value/set_debug_value.",
                },
                "value": {
                    "type": "string",
                    "description": "String value for set_debug_value.",
                },
            },
            "additionalProperties": False,
        },
    },
}


cancer_control.tool_timeout_seconds = 3600


__all__ = ["cancer_control", "cancer_control_declaration"]
