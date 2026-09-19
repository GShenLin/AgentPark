"""Review notices carry evidence; node memory is maintained by its own pipeline."""
from __future__ import annotations


def _context(payload: dict) -> list[str]:
    source, run, report = payload["source"], payload["run"], payload["report"]
    graph = source.get("graph_id") or "unknown"
    lines = [f"Node: {graph}/{source.get('node_id') or 'unknown'}"]
    fields = [(source, "node_type_id", "Node type"), (source, "provider", "Provider"),
              (run, "trace_id", "Trace ID"), (run, "duration_ms", "Duration ms"),
              (run, "goal_status", "Goal status after run"), (run, "goal_reason", "Goal reason"),
              (report, "memory_path", "Memory file"), (report, "messages_path", "Structured messages file"),
              (report, "runtime_events_path", "Runtime events file"),
              (run, "input_preview", "Input preview"), (run, "output_preview", "Output preview")]
    for data, key, label in fields:
        if data.get(key) is not None and data[key] != "":
            lines.append(f"{label}: {data[key]}")
    if run.get("from_node"):
        lines.append(f"Triggered by node: {graph}/{run['from_node']}")
    return lines


def format_node_review(payload: dict) -> str:
    return "\n".join(["A node run was persisted.", *_context(payload), "Review scope:",
        "- Reconstruct the run from persisted messages and runtime events, including tool calls, tool results, and final answer.",
        "- Judge whether the requested result is achieved, partially achieved, blocked, or not achieved.",
        "- Provide concrete evidence for actionable improvements to code, environment, and answer quality.",
        "- Each node consolidates its own long-term memory. Do not edit another node's memory.",
        "- Do not write a separate review report unless the user explicitly asks for one."])


def format_tool_failure(payload: dict) -> str:
    lines = ["A tool call failed in an Agent node. Review the persisted evidence.", *_context(payload)]
    failure = payload.get("failure") or {}
    for key, label in [("tool_name", "Failed tool"), ("call_id", "Tool call ID"),
                       ("status", "Failure status"), ("error", "Error"), ("result_preview", "Tool result preview")]:
        if failure.get(key):
            lines.append(f"{label}: {failure[key]}")
    for item in (payload.get("context") or {}).get("recent_messages", []):
        if isinstance(item, dict) and item.get("text"):
            lines.append(f"- {item.get('role') or 'message'}: {item['text']}")
    lines.append("Each node consolidates its own long-term memory. Do not edit another node's memory.")
    return "\n".join(lines)
