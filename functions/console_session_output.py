"""Disk-backed, strictly decoded output with replayable character cursors."""

import codecs
import threading


class SessionOutput:
    MAX_CHARS = 16 * 1024 * 1024

    def __init__(self, path, pipe, condition):
        self.path = path
        self.pipe = pipe
        self.condition = condition
        self.length = 0
        self.error = None
        self.finished = False
        self.thread = threading.Thread(target=self._drain, daemon=True, name="console-session-output")
        path.touch()
        self.thread.start()

    def _drain(self):
        decoder = codecs.getincrementaldecoder("utf-8")("strict")
        try:
            with self.path.open("wb") as stream:
                while True:
                    chunk = self.pipe.read1(8192)
                    text = decoder.decode(chunk, final=not chunk)
                    if self.length + len(text) > self.MAX_CHARS:
                        raise ValueError(f"Session output exceeded the {self.MAX_CHARS}-character per-stream limit")
                    with self.condition:
                        stream.write(text.encode("utf-32-le"))
                        stream.flush()
                        self.length += len(text)
                        self.condition.notify_all()
                    if not chunk:
                        break
        except Exception as exc:
            with self.condition:
                self.error = f"{type(exc).__name__}: {exc}"
        finally:
            self.pipe.close()
            with self.condition:
                self.finished = True
                self.condition.notify_all()

    def read(self, offset, limit):
        # Caller holds the shared condition lock; fixed-width spool permits exact
        # character offsets even when UTF-8 input split a multibyte character.
        if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= self.length:
            raise ValueError("Output cursor is outside the retained stream")
        with self.path.open("rb") as stream:
            stream.seek(offset * 4)
            return stream.read(min(limit, self.length - offset) * 4).decode("utf-32-le")
