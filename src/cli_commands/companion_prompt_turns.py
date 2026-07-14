from __future__ import annotations

import threading
from typing import Any, Callable


TurnRunner = Callable[[Any, str, bool], dict[str, Any]]
TextCallback = Callable[[str], None]
VoidCallback = Callable[[], None]
TurnStateCallback = Callable[[str], None]
StreamCallback = Callable[[dict[str, Any]], None]


class PromptTurnCoordinator:
    def __init__(
        self,
        target: Any,
        *,
        run_turn: TurnRunner,
        turn_lock: threading.Lock,
        print_user: TextCallback,
        print_status: TextCallback,
        print_error: TextCallback,
        after_turn: VoidCallback,
        begin_turn: TurnStateCallback,
        submit_mid_turn: TextCallback,
        finish_turn: VoidCallback,
    ) -> None:
        self.target = target
        self.run_turn = run_turn
        self.turn_lock = turn_lock
        self.print_user = print_user
        self.print_status = print_status
        self.print_error = print_error
        self.after_turn = after_turn
        self.begin_turn = begin_turn
        self.submit_mid_turn = submit_mid_turn
        self.finish_turn = finish_turn
        self._state_lock = threading.Lock()
        self._idle = threading.Event()
        self._idle.set()
        self._running = False
        self._stream_handler: StreamCallback | None = None

    @property
    def running(self) -> bool:
        with self._state_lock:
            return self._running

    def submit(self, text: str) -> None:
        message = str(text or "")
        mid_turn_error: Exception | None = None
        with self._state_lock:
            running = self._running
            if running:
                try:
                    self.submit_mid_turn(message)
                except Exception as exc:
                    mid_turn_error = exc
            else:
                self._running = True
                self._idle.clear()
        if running:
            self.print_user(message)
            if mid_turn_error is None:
                self.print_status("input will be included at the next function call")
            else:
                self.print_error(f"{type(mid_turn_error).__name__}: {mid_turn_error}")
            return
        threading.Thread(
            target=self._run_turn,
            args=(message,),
            name="companion-prompt-turn",
            daemon=True,
        ).start()

    def wait_until_idle(self, timeout: float | None = None) -> bool:
        return self._idle.wait(timeout=timeout)

    def set_stream_handler(self, handler: StreamCallback | None) -> None:
        with self._state_lock:
            if self._running:
                raise RuntimeError("cannot change the prompt stream handler while a turn is running")
            self._stream_handler = handler

    def _run_turn(self, message: str) -> None:
        self.print_user(message)
        self.print_status("working")
        try:
            self.begin_turn(message)
            with self.turn_lock:
                if self._stream_handler is None:
                    self.run_turn(self.target, message, print_stream=True)
                else:
                    self.run_turn(
                        self.target,
                        message,
                        print_stream=False,
                        stream_handler=self._stream_handler,
                    )
        except KeyboardInterrupt:
            self.print_error("interrupted")
        except Exception as exc:
            self.print_error(f"{type(exc).__name__}: {exc}")
        finally:
            try:
                self.after_turn()
            except Exception as exc:
                self.print_error(f"{type(exc).__name__}: {exc}")
            with self._state_lock:
                try:
                    self.finish_turn()
                except Exception as exc:
                    self.print_error(f"{type(exc).__name__}: {exc}")
                self._running = False
                self._idle.set()


__all__ = ["PromptTurnCoordinator"]
