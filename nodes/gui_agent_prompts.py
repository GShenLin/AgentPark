ACTION_FORMAT_HINT = (
    "Allowed Action forms:\n"
    "Action: click(point='<point>x y</point>')\n"
    "Action: left_double(point='<point>x y</point>')\n"
    "Action: right_single(point='<point>x y</point>')\n"
    "Action: drag(start_point='<point>x1 y1</point>', end_point='<point>x2 y2</point>')\n"
    "Action: type(content='text')\n"
    "Action: scroll(direction='down', point='<point>x y</point>')\n"
    "Action: long_press(point='<point>x y</point>')\n"
    "Action: wait\n"
    "Action: finished(content='done')\n"
    "Action: press_back\n"
    "Action: press_home\n"
    "Coordinates must be normalized 0-1000 values relative to screenshot width/height."
)


def format_recent_history(history: list[dict], limit: int = 6) -> str:
    history_lines = []
    for item in history[-limit:]:
        idx = int(item.get("step") or 0)
        action_text = str(item.get("action") or "")
        result_text = str(item.get("result") or "")
        history_lines.append(f"{idx}. action={action_text}; result={result_text}")
    return "\n".join(history_lines) if history_lines else "(none)"


def build_planner_prompt(instruction: str, step_index: int, history: list[dict]) -> str:
    history_text = format_recent_history(history)
    return (
        f"Task: {instruction}\n"
        f"Step: {step_index}\n"
        f"Recent history:\n{history_text}\n"
        f"{ACTION_FORMAT_HINT}\n"
        "Rules:\n"
        "- Return exactly two lines.\n"
        "- First line starts with 'Thought:'.\n"
        "- Second line starts with 'Action:'.\n"
        "- Use only one action in function-call style.\n"
        "- Do not return JSON.\n"
        "- If latest result has screen_changed=false, treat it as ineffective and choose a different target/action."
    )


def build_action_repair_prompt(
    instruction: str,
    step_index: int,
    history: list[dict],
    bad_response: str,
    bad_action_text: str,
    bad_action_name: str,
    execution_error: str = "",
) -> str:
    history_text = format_recent_history(history)
    execution_error_line = f"Execution error: {execution_error}\n" if execution_error else ""
    return (
        f"Task: {instruction}\n"
        f"Step: {step_index}\n"
        f"Recent history:\n{history_text}\n"
        "Your previous answer is not executable by the GUI executor.\n"
        f"Previous planner response:\n{bad_response}\n"
        f"Parsed action text: {bad_action_text}\n"
        f"Parsed action name: {bad_action_name}\n"
        f"{execution_error_line}"
        f"{ACTION_FORMAT_HINT}\n"
        "Rules:\n"
        "- Return exactly two lines.\n"
        "- First line starts with 'Thought:'.\n"
        "- Second line starts with 'Action:'.\n"
        "- Use only one action in function-call style.\n"
        "- Do not return JSON.\n"
        "- If latest result has screen_changed=false, treat it as ineffective and choose a different target/action.\n"
        "- Do not output natural language instructions.\n"
        "- The action name must be one of: click, left_double, right_single, drag, type, scroll, wait, finished, long_press, press_back, press_home."
    )
