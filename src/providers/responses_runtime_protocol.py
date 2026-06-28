from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class ResponsesStreamText:
    text: str = ""

    def reset(self) -> None:
        self.text = ""

    def update(self, delta_text: Any, full_text: Any) -> str:
        if full_text is None:
            self.text += str(delta_text or "")
        else:
            self.text = str(full_text or "")
        return self.text


def is_previous_response_missing_error(error: Any) -> bool:
    text = str(error or "")
    return "PreviousResponseNotFound" in text or (
        "previous_response_id" in text and "not found" in text
    )


@dataclass(frozen=True)
class ResponsesRuntimeModeDecision:
    requested_mode: str
    mode: str
    fallback_reason: str = ""
