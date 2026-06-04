from __future__ import annotations

from collections.abc import Callable
import inspect

from src.node_stream_protocol import build_node_message_delta
from src.node_stream_protocol import build_node_message_done


StreamCallback = Callable[[dict], None]


class AgentStreamRuntime:
    def __init__(self, stream_callback: StreamCallback | None, *, suppress_callback_errors: bool = False):
        self.stream_callback = stream_callback if callable(stream_callback) else None
        self.suppress_callback_errors = bool(suppress_callback_errors)
        self.streamed_text = ""

    def on_stream_delta(self, delta: object, full_text: object | None = None) -> None:
        delta_text = str(delta or "")
        if full_text is None:
            self.streamed_text = self.streamed_text + delta_text
        else:
            self.streamed_text = str(full_text or "")
        self._emit(build_node_message_delta(delta_text, self.streamed_text))

    def on_tool_event(self, event: object) -> None:
        if isinstance(event, dict):
            self._emit(dict(event))

    def send(self, agent: object, requested_kwargs: dict) -> object:
        previous_tool_event_callback = getattr(agent, "tool_event_callback", None)
        agent.tool_event_callback = self.on_tool_event
        try:
            kwargs = self._supported_send_kwargs(agent, requested_kwargs)
            if kwargs:
                return agent.Send(**kwargs)
            return agent.Send()
        finally:
            agent.tool_event_callback = previous_tool_event_callback

    def emit_done(self, final_text: object) -> None:
        text = str(final_text or "")
        if text and text != self.streamed_text:
            delta_text = text[len(self.streamed_text) :] if text.startswith(self.streamed_text) else text
            self._emit(build_node_message_delta(delta_text, text, force=True))
        self._emit(build_node_message_done(text))

    def _emit(self, payload: dict) -> None:
        if not callable(self.stream_callback):
            return
        try:
            self.stream_callback(dict(payload))
        except Exception:
            if self.suppress_callback_errors:
                return
            raise

    @staticmethod
    def _supported_send_kwargs(agent: object, requested_kwargs: dict) -> dict:
        send = getattr(agent, "Send", None)
        if not callable(send):
            raise TypeError("agent must expose a callable Send method")
        try:
            signature = inspect.signature(send)
        except (TypeError, ValueError) as exc:
            raise TypeError("cannot inspect agent Send signature") from exc

        params = signature.parameters
        accepts_any_kwargs = any(param.kind == inspect.Parameter.VAR_KEYWORD for param in params.values())
        if accepts_any_kwargs:
            return dict(requested_kwargs)

        supported_names = {
            name
            for name, param in params.items()
            if param.kind in {inspect.Parameter.POSITIONAL_OR_KEYWORD, inspect.Parameter.KEYWORD_ONLY}
        }
        supported_names.discard("self")
        return {key: value for key, value in requested_kwargs.items() if key in supported_names}
