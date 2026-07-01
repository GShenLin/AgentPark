from __future__ import annotations


COMPANION_MCP_INSTRUCTIONS = """
AgentPark companion is a graph/node coordination MCP.

Typical workflow:
1. Call get_companion_meta first. Use it to confirm your graph_id/node_id, working_path, version, and capabilities before any conclusion.
2. Use get_working_node for a quick busy-node check, then list_node_status to pick a worker by state, working_path, last_error, and capabilities.can.
3. Use list_link when graph topology matters; use connect_node/disconnect_node to change links within one graph only.
4. Do not infer project facts before reading authoritative files or node output. Delegate file, shell, web, or project work to a worker that has the needed can.* capability.
5. Call send_message_to_node with wait_until_idle=true for normal delegation. Use clear_history=true only when stale errors or irrelevant context would pollute the run.
6. If the returned node.wait.timeout is true, the node may still be working. Follow node.wait.next_action: continue get_node_last_message with wait_until_idle=true, or call stop_node if it is stuck.
7. If node.last_message_truncated is true, or the answer says it is abbreviated, call get_node_memory with pagination when needed for fuller recent context.
""".strip()


__all__ = ["COMPANION_MCP_INSTRUCTIONS"]
