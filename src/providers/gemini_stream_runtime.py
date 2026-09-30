import json
from src.providers.curl_transport import CurlHttpTransport, CurlResponse, CurlHttpError
from typing import Callable

from src.providers.provider_pressure import acquire_provider_pressure
from src.providers.provider_runtime_events import ProviderRuntimeEventMixin
from src.providers.provider_stream_emit import ProviderStreamEmitMixin
from src.service_host import HostBoundService


class GeminiStreamRuntime(ProviderStreamEmitMixin, ProviderRuntimeEventMixin, HostBoundService):
    def _stream_generate_content_once(self, *, url: str, headers: dict, payload_json: str, timeout_sec: float, stream_handler):
        full_text = ""
        latest_function_calls: list[dict] = []
        inline_image_parts: list[dict] = []
        seen_inline_images: set[tuple[str, str]] = set()

        transport = CurlHttpTransport()
        transport.cancel_event = getattr(self, "cancel_event", None)
        with acquire_provider_pressure(self):
            for data_text in transport.stream_sse_data(url=url, headers=headers or {},
                    payload_json=payload_json, timeout_sec=timeout_sec):
                if isinstance(data_text, CurlResponse):
                    data_text.raise_for_status()
                    continue
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
                for part in parts:
                    if not isinstance(part, dict):
                        continue
                    inline = part.get("inlineData") or part.get("inline_data")
                    if not isinstance(inline, dict):
                        continue
                    mime_type = str(inline.get("mimeType") or inline.get("mime_type") or "").strip()
                    data = str(inline.get("data") or "").strip()
                    if not mime_type.lower().startswith("image/") or not data:
                        continue
                    key = (mime_type.lower(), data)
                    if key in seen_inline_images:
                        continue
                    seen_inline_images.add(key)
                    inline_image_parts.append(part)
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
        parts_out.extend(inline_image_parts)

        return {"candidates": [{"content": {"parts": parts_out}}]}
