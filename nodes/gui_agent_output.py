from datetime import datetime

from src.message_protocol import build_resource_part, normalize_envelope


def build_gui_agent_response(
    *,
    status: str,
    finished: bool,
    final_reason: str,
    instruction: str,
    run_dir: str,
    step_logs: list[dict],
    screenshot_paths: list[str],
    provider_id: str,
    planner_mode: str,
    verify_mode: str,
    dry_run: bool,
    verify_on_finish: bool,
    planner_timeout_seconds: float,
    verify_timeout_seconds: float,
) -> dict:
    summary_text = "\n".join(
        [
            f"GUI loop {status}.",
            f"instruction: {instruction}",
            f"steps: {len(step_logs)}",
            f"reason: {final_reason}",
            f"run_dir: {run_dir}",
        ]
    )
    parts: list[dict] = [{"type": "text", "text": summary_text}]
    for img_path in screenshot_paths[-6:]:
        parts.append(build_resource_part(uri=img_path, kind="image", source="gui_agent"))
    parts.append(
        {
            "type": "structured",
            "data": {
                "status": status,
                "finished": finished,
                "reason": final_reason,
                "instruction": instruction,
                "steps": step_logs,
                "run_dir": run_dir,
                "planner_provider_id": provider_id,
                "mode": planner_mode,
                "verify_mode": verify_mode,
                "dry_run": dry_run,
                "verify_on_finish": verify_on_finish,
                "planner_timeout_seconds": planner_timeout_seconds,
                "verify_timeout_seconds": verify_timeout_seconds,
                "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
            },
        }
    )

    output = normalize_envelope({"role": "assistant", "parts": parts}, default_role="assistant")
    return {
        "display": summary_text,
        "routes": [{"output_index": 0, "payload": output}],
    }
