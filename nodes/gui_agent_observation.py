import os

from nodes.gui_agent_markers import draw_action_marker, image_change_ratio, image_signature


def update_screen_change_result(
    *,
    exec_result: dict,
    before_path: str,
    after_path: str,
    after_capture_ok: bool,
    min_screen_change_ratio: float,
) -> dict:
    screen_changed: bool | None = None
    before_sig = _safe_image_signature(before_path)
    after_sig = _safe_image_signature(after_path) if after_capture_ok else ""
    if before_sig and after_sig:
        screen_changed = before_sig != after_sig
        change_ratio = image_change_ratio(before_path, after_path)
        if change_ratio >= 0:
            exec_result["change_ratio"] = round(change_ratio, 6)
            if change_ratio < float(min_screen_change_ratio):
                screen_changed = False
    exec_result["screen_changed"] = screen_changed
    if screen_changed is False:
        exec_result["effect"] = "no_visible_change"
    return {
        "screen_changed": screen_changed,
        "before_signature": before_sig,
        "after_signature": after_sig,
    }


def mark_action_feedback_image(
    *,
    run_dir: str,
    step_index: int,
    after_path: str,
    action_name: str,
    parsed: dict,
    exec_result: dict,
) -> tuple[str, dict]:
    if action_name not in {"click", "left_double", "right_single", "long_press", "drag", "scroll"}:
        return after_path, {}

    marked_path = os.path.join(run_dir, f"step_{step_index:02d}_after_marked.png")
    try:
        mark_ok, mark_error, marker_meta = draw_action_marker(
            image_path=after_path,
            action_name=action_name,
            parsed=parsed,
            exec_result=exec_result,
            save_path=marked_path,
        )
    except Exception as e:
        exec_result["after_marked"] = False
        return after_path, {"screenshot_after_marked_error": str(e)}

    if not mark_ok:
        exec_result["after_marked"] = False
        return after_path, {"screenshot_after_marked_error": str(mark_error or "")}

    exec_result["after_marked"] = True
    if isinstance(marker_meta, dict) and marker_meta:
        exec_result["marked_coordinates"] = marker_meta
    return marked_path, {
        "screenshot_after_raw": after_path,
        "screenshot_after_marked": marked_path,
    }


def _safe_image_signature(path: str) -> str:
    try:
        return image_signature(path)
    except Exception:
        return ""
