"""In-host asynchronous Harness turns share the host's resident process owner.

Unlike disposable node workers, these turns must not fork a second owner of the
same native session. The run handle cancels a turn; native process ownership stays
with HarnessProcesses and is visible to the node and installation APIs.
"""
import threading

from src.runtime_cancellation import CancellationSignal


class HarnessRun:
    pid = None

    def __init__(self, target, args, context):
        self.cancel = CancellationSignal()
        context["cancel_event"] = self.cancel
        self.thread = threading.Thread(target=target, args=args, daemon=True, name="harness-turn")

    def start(self):
        self.thread.start()

    def is_alive(self):
        return self.thread.is_alive()

    def join(self, timeout=None):
        self.thread.join(timeout)

    def terminate(self):
        self.cancel.set()
