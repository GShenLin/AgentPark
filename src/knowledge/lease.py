"""A workspace has one indexing supervisor even when multiple servers are launched."""
import os


class WorkspaceLease:
    def __init__(self, path):
        self.path = path
        self.stream = None

    def acquire(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        stream = self.path.open("a+b")
        if stream.tell() == 0:
            stream.write(b"0")
            stream.flush()
        stream.seek(0)
        try:
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            stream.close()
            raise RuntimeError("另一个 AgentPark 进程正在管理此工作区的 Knowledge 索引") from exc
        self.stream = stream

    def close(self):
        if self.stream:
            # Closing the descriptor releases its OS lock, including on process death.
            self.stream.close()
            self.stream = None
