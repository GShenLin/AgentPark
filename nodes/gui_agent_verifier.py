import json
import re

from src.value_parsing import parse_bool_value


def build_verify_prompt(verify_prompt: str, instruction: str, planner_response: str) -> str:
    return (
        f"{verify_prompt}\n"
        f"Task: {instruction}\n"
        f"Planner output:\n{planner_response}\n"
        "JSON only."
    )


def parse_verify_response(text: object) -> tuple[bool, str]:
    response_text = "" if text is None else str(text)
    json_match = re.search(r"\{[\s\S]*\}", response_text)
    if json_match:
        try:
            payload = json.loads(json_match.group(0))
        except Exception:
            payload = None
        if isinstance(payload, dict):
            parsed = _parse_verify_payload(payload)
            if parsed is not None:
                return parsed
    return False, response_text[:160]


def _parse_verify_payload(payload: dict) -> tuple[bool, str] | None:
    if "done" in payload:
        done = parse_bool_value(payload.get("done"), default=False)
        reason = str(payload.get("reason") or payload.get("content") or "").strip()
        return done, reason

    name_text = str(payload.get("name") or "").strip().lower()
    if name_text == "finished":
        params = payload.get("parameters")
        if isinstance(params, dict):
            reason = str(params.get("content") or payload.get("reason") or "").strip()
        else:
            reason = str(payload.get("content") or payload.get("reason") or "").strip()
        return True, reason[:160]

    action_text = str(payload.get("action") or "").strip().lower()
    if action_text == "finished":
        reason = str(payload.get("reason") or payload.get("content") or "").strip()
        return True, reason[:160]

    content_text = str(payload.get("content") or "").strip()
    content_key = content_text.lower()
    if content_key in {"done", "completed", "finished", "success", "ok", "瀹屾垚"}:
        reason = str(payload.get("reason") or content_text).strip()
        return True, reason[:160]
    return None
