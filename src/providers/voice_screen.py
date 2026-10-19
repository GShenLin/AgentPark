"""A call-owned image sink. Pixels stay between execution hosts and providers."""
from abc import ABC, abstractmethod
from collections.abc import Callable

from src.desktop_capture.contracts import CapturedFrame


class VoiceScreenSink(ABC):
    @abstractmethod
    def publish(self, session_id: str, frame: CapturedFrame, current: Callable[[], bool]) -> str:
        """Return the provider item ID only after insertion is acknowledged."""

    @abstractmethod
    def close(self) -> None:
        """Close owned connections without ending the audio transport."""
