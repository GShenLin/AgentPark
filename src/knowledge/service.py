import multiprocessing
import threading
import time
from pathlib import Path

from .catalog import Catalog
from .database import Database
from .scanner import begin_scan
from .lease import WorkspaceLease
from .worker import run_pipeline


class KnowledgeService:
    """One supervised worker process per workspace; large libraries queue durably."""

    def __init__(self, workspace: Path):
        self.catalog = Catalog(workspace)
        self._lock = threading.RLock()
        self._closed = threading.Event()
        self._context = multiprocessing.get_context("spawn")
        self._process = None
        self._stop = None
        self._active = None
        self._thread = None
        self._initialized = threading.Event()
        self.error = ""
        self._lease = WorkspaceLease(Path(workspace) / "data" / "knowledge" / "supervisor.lock")

    def store(self, key):
        store = Database(self.catalog.directory(key))
        store.initialize()
        return store

    def list(self):
        return {"libraries": [{**item, "progress": self.store(item["id"]).status()}
                              for item in self.catalog.list()], "worker_error": self.error}

    def start(self):
        with self._lock:
            if self._thread is not None:
                return
            self._lease.acquire()
            self._closed.clear()
            self._initialized.clear()
            self._thread = threading.Thread(target=self._monitor, name="knowledge-supervisor", daemon=True)
            self._thread.start()

    def _monitor(self):
        try:
            # A process lost in a previous application exit resumes from its durable phase.
            for item in self.catalog.list():
                with self.store(item["id"]).connect() as db:
                    db.execute("UPDATE job SET status='queued' WHERE status IN ('running','stopping')")
            self._initialized.set()
            while not self._closed.is_set():
                with self._lock:
                    if self._process is not None and not self._process.is_alive():
                        self._process.join()
                        store = self.store(self._active)
                        with store.connect() as db:
                            db.execute("UPDATE job SET status='failed',error=? WHERE status IN ('running','stopping')",
                                       (f"索引进程退出，exit code {self._process.exitcode}；可继续任务",))
                        self._process.close()
                        self._process = self._stop = self._active = None
                    if self._process is None:
                        for item in self.catalog.list():
                            if self.store(item["id"]).status()["status"] == "queued":
                                self._active = item["id"]
                                self._stop = self._context.Event()
                                self._process = self._context.Process(target=run_pipeline, args=(
                                    str(self.catalog.workspace), self._active, self._stop), daemon=True)
                                self._process.start()
                                break
                self._closed.wait(1)
        except Exception as exc:
            self.error = f"Knowledge supervisor failed: {type(exc).__name__}: {exc}"
            self._initialized.set()

    def operate(self, key, action):
        with self._lock:
            self.start()
            if not self._initialized.wait(30):
                raise RuntimeError("Knowledge supervisor startup timed out")
            if self.error:
                raise RuntimeError(self.error)
            store = self.store(key)
            state = store.status()
            active = self._active == key and self._process is not None and self._process.is_alive()
            if action == "pause":
                if active:
                    self._stop.set()
                with store.connect() as db:
                    db.execute("UPDATE job SET status=? WHERE id=1", ("stopping" if active else "paused",))
            elif active or state["status"] == "queued":
                raise RuntimeError("知识库任务已在运行或排队")
            elif action == "scan":
                if state["phase"] != "idle" and state["status"] not in {"idle", "completed", "completed_with_errors"}:
                    raise RuntimeError("请先继续当前任务；完成后可启动增量扫描")
                begin_scan(store)
            elif action == "retry":
                if state["phase"] in {"scan", "prune"}:
                    raise RuntimeError("请先继续并完成目录扫描")
                with store.connect() as db:
                    db.execute("UPDATE documents SET state='pending',error='' WHERE state='error'")
                    db.execute("UPDATE job SET status='queued',phase='parse',error='' WHERE id=1")
            elif action == "resume":
                if state["phase"] == "idle":
                    raise ValueError("没有待继续的任务，请启动增量扫描")
                with store.connect() as db:
                    db.execute("UPDATE job SET status='queued',error='' WHERE id=1")
            else:
                raise ValueError("未知操作")
            self.start()
            return store.status()

    def update(self, key, payload):
        with self._lock:
            if self.store(key).status()["status"] in {"queued", "running", "stopping"}:
                raise RuntimeError("请暂停索引任务后修改配置")
            return self.catalog.update(key, payload)

    def test_embedding(self, key):
        from .embedding import Embedder

        with self._lock:
            if self.store(key).status()["status"] in {"queued", "running", "stopping"}:
                raise RuntimeError("索引任务正在运行，请暂停后测试模型")
            config = self.catalog.get(key)
            dimensions = Embedder(config, workspace=self.catalog.workspace).detect_dimensions()
            self.catalog.bind_dimensions(key, dimensions)
            return {"ok": True, "dimensions": dimensions}

    def close(self):
        self._closed.set()
        if self._thread:
            self._thread.join(timeout=3)
        with self._lock:
            if self._process:
                was_stopping = self.store(self._active).status()["status"] == "stopping"
                self._stop.set()
                self._process.join(timeout=3)
                if self._process.is_alive():
                    self._process.terminate()
                    self._process.join(timeout=3)
                if self._process.is_alive():
                    raise RuntimeError("Knowledge worker did not stop")
                with self.store(self._active).connect() as db:
                    db.execute("UPDATE job SET status=? WHERE status IN ('paused','running','stopping')",
                               ("paused" if was_stopping else "queued",))
                self._process.close()
                self._process = self._stop = self._active = None
            self._thread = None
            self._lease.close()
