import json
import urllib.request
from typing import Callable

from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.service_host import HostBoundService


class GeminiStreamRuntime(ProviderStreamEmitMixin, ProviderRuntimeEventMixin, HostBoundService):
    def _stream_generate_content_once(self, *, url: str, headers: dict, payload_json: str, timeout_sec: float, stream_handler):
        req = urllib.request.Request(
            str(url),
            data=str(payload_json).encode("utf-8"),
            headers=headers or {},
            method="POST",
        )

        full_text = ""
        latest_function_calls: list[dict] = []

        with urllib.request.urlopen(req, timeout=max(1, float(timeout_sec or 60))) as response:
            if int(getattr(response, "status", 200) or 200) != 200:
                raw = response.read()
                body = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else str(raw)
                raise RuntimeError(f"HTTP Error: {getattr(response, 'status', 0)} - {body}")

            for raw_line in response:
                line = raw_line.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("data:"):
                    continue
                data_text = line[5:].strip()
                if not data_text or data_text == "[DONE]":
                    continue
                event = self._parse_sse_json_event(data_text, stage="gemini_stream_parse")
                if event is None:
                    continue
                candidates = event.get("candidates") if isinstance(event, dict) else None
                if not isinstance(candidates, list) or not candidates:
                    continue
                candidate = candidates[0]
                if not isinstance(candidate, dict):
                    continue
                content = candidate.get("content") if isinstance(candidate.get("content"), dict) else {}
                parts = content.get("parts") if isinstance(content.get("parts"), list) else []
                function_calls, text_content, has_text = self._extract_candidate_calls_and_text(parts)
                if function_calls:
                    latest_function_calls = function_calls
                if has_text:
                    if text_content.startswith(full_text):
                        delta_text = text_content[len(full_text) :]
                        full_text = text_content
                    else:
                        delta_text = text_content
                        full_text = full_text + text_content
                    if delta_text:
                        self._emit_stream_text(stream_handler, delta_text, full_text)

        parts_out = []
        if full_text:
            parts_out.append({"text": full_text})
        for call in latest_function_calls:
            if isinstance(call, dict):
                parts_out.append({"functionCall": call})

        return {"candidates": [{"content": {"parts": parts_out}}]}
