import json
import os
from datetime import datetime


class OpenAIResponsesHttpDebugMixin:
    @staticmethod
    def _summarize_responses_payload(payload_json):
        try:
            payload = json.loads(str(payload_json or ""))
        except Exception:
            return {"payload_parse_error": True}
        if not isinstance(payload, dict):
            return {"payload_type": type(payload).__name__}
        items = []
        for item in payload.get("input") if isinstance(payload.get("input"), list) else []:
            if not isinstance(item, dict):
                continue
            item_type = str(item.get("type") or "").strip()
            summary = {"type": item_type, "type_present": "type" in item}
            for key in ("id", "call_id", "name", "role", "status"):
                if item.get(key) is not None:
                    summary[key] = str(item.get(key) or "")
            items.append(summary)
        return {
            "model": str(payload.get("model") or ""),
            "previous_response_id": str(payload.get("previous_response_id") or ""),
            "stream": bool(payload.get("stream")),
            "input": items,
        }

    def _write_responses_http_debug(self, *, url, payload_json, status_code, response_body):
        try:
            root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            debug_dir = os.path.join(root, ".runtime")
            os.makedirs(debug_dir, exist_ok=True)
            entry = {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S.%f"),
                "url": str(url or ""),
                "status_code": int(status_code or 0),
                "payload": self._summarize_responses_payload(payload_json),
                "response_body": str(response_body or "")[:4000],
            }
            with open(os.path.join(debug_dir, "openai_responses_debug.jsonl"), "a", encoding="utf-8") as handle:
                handle.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception:
            return
