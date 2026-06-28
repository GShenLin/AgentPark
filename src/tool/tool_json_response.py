from __future__ import annotations

import json
from typing import Any


def tool_json_payload(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False)


def tool_json_error(message: object, **extra: Any) -> str:
    payload = {"status": "error", "error": str(message)}
    payload.update(extra)
    return tool_json_payload(payload)
