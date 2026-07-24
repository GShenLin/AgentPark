import multiprocessing
import json
import os
import threading
import traceback
from datetime import datetime

from src.memory_root import get_memories_root
from src.providers import create_agent


def _run_leader_session(task_id, provider_id, memory_file_path, tool_names, inbox):
    try:
        agent = create_agent(provider_id, memory_file_path=memory_file_path)
        if tool_names:
            for name in tool_names:
                agent.addTool(name)
        print(f"\n[Leader:{task_id}] Started pid={os.getpid()}\n", flush=True)

        while True:
            item = inbox.get()
            if item is None:
                continue

            if isinstance(item, dict):
                if item.get("type") == "shutdown":
                    break
                message = item.get("message")
                if message is None:
                    message = item.get("task")
            else:
                message = item

            message = str(message or "").strip()
            if not message:
                continue

            result = agent.makePlan(message)
            print(f"\n[Leader:{task_id}] Done\n{result}\n", flush=True)
    except Exception as e:
        print(f"\n[Leader:{task_id}] Error: {e}\n", flush=True)
        traceback.print_exc()


class BasePlaner:
    def __init__(self, leader_provider_id, tool_names=None, start_method="spawn"):
        self.leader_provider_id = leader_provider_id
        self.tool_names = list(tool_names or [])
        self._ctx = multiprocessing.get_context(start_method) if start_method else multiprocessing.get_context()
        self._tasks = {}
        self._history = {}
        self._next_task_id = 1
        self._lock = threading.RLock()

    def _sanitize_for_dirname(self, text, limit=60):
        s = str(text or "").strip()
        if not s:
            return "task"
        s = " ".join(s.split())
        s = s.replace(" ", "_")
        invalid = '<>:"/\\|?*'
        s = "".join(ch for ch in s if ch not in invalid)
        s = s.strip(" ._")
        if not s:
            s = "task"
        if len(s) > limit:
            s = s[:limit]
        return s

    def _build_leader_memory_file_path(self, user_task):
        agents_root = os.path.join(get_memories_root(), "agents")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        task_part = self._sanitize_for_dirname(user_task)
        run_dir = os.path.join(agents_root, f"{ts}_{task_part}")
        os.makedirs(run_dir, exist_ok=True)
        
        # Isolate LeaderAgent in its own folder
        leader_dir = os.path.join(run_dir, "LeaderAgent")
        os.makedirs(leader_dir, exist_ok=True)
        return os.path.join(leader_dir, "LeaderAgent.md")

    def submit(self, user_task):
        task = str(user_task or "").strip()
        if not task:
            raise ValueError("Empty task.")

        with self._lock:
            task_id = self._next_task_id
            self._next_task_id += 1
            leader_memory_path = self._build_leader_memory_file_path(task)
            try:
                leader_dir = os.path.dirname(leader_memory_path)
                if leader_dir:
                    os.makedirs(leader_dir, exist_ok=True)
                if leader_memory_path and not os.path.exists(leader_memory_path):
                    with open(leader_memory_path, "a", encoding="utf-8"):
                        pass
            except Exception:
                pass

            inbox = self._ctx.Queue()
            proc = self._ctx.Process(
                target=_run_leader_session,
                args=(task_id, self.leader_provider_id, leader_memory_path, self.tool_names, inbox),
                name=f"LeaderPlan-{task_id}",
            )
            proc.daemon = False
            proc.start()
            self._tasks[task_id] = {
                "process": proc,
                "pid": proc.pid,
                "task": task,
                "memory_path": leader_memory_path,
                "inbox": inbox,
                "started_at": datetime.now(),
                "finished_at": None,
                "exitcode": None,
            }
            try:
                inbox.put({"type": "user_message", "message": task})
            except Exception:
                pass
            self.cleanup_finished()
            return task_id, proc.pid

    def send_to_leader(self, task_id: int, message: str) -> bool:
        msg = str(message or "").strip()
        if not msg:
            return False

        with self._lock:
            info = self._tasks.get(task_id)
        if not info:
            return False

        proc = info.get("process")
        if proc is None:
            return False
        try:
            if not proc.is_alive():
                return False
        except Exception:
            return False

        inbox = info.get("inbox")
        if inbox is None:
            return False
        try:
            inbox.put({"type": "user_message", "message": msg})
            return True
        except Exception:
            return False

    def cleanup_finished(self):
        with self._lock:
            finished = [tid for tid, info in self._tasks.items() if not info["process"].is_alive()]
            for tid in finished:
                info = self._tasks.pop(tid, None)
                if not info:
                    continue
                proc = info.get("process")
                if proc is not None:
                    proc.join(timeout=0)
                    info["exitcode"] = proc.exitcode
                info["finished_at"] = info.get("finished_at") or datetime.now()
                self._history[tid] = info

    def wait(self, task_id, timeout=None):
        with self._lock:
            info = self._tasks.get(task_id) or self._history.get(task_id)
        if not info:
            return
        proc = info.get("process")
        if proc is not None and proc.is_alive():
            proc.join(timeout=timeout)
        self.cleanup_finished()

    def wait_all(self):
        for tid in list(self._tasks.keys()):
            self.wait(tid)

    def terminate(self, task_id):
        with self._lock:
            info = self._tasks.get(task_id) or self._history.get(task_id)
        if not info:
            return
        proc = info.get("process")
        if proc is None:
            return
        inbox = info.get("inbox")
        if proc.is_alive():
            if inbox is not None:
                try:
                    inbox.put({"type": "shutdown"})
                except Exception:
                    pass
            proc.join(timeout=3)
            if proc.is_alive():
                proc.terminate()
                proc.join(timeout=3)
        self.cleanup_finished()

    def _parse_first_json_object(self, text):
        if not isinstance(text, str) or not text:
            return None
        start = text.find("{")
        end = text.rfind("}")
        if start == -1 or end == -1 or end <= start:
            return None
        candidate = text[start : end + 1]
        try:
            return json.loads(candidate)
        except Exception:
            return None

    def _collect_subagents_from_memory(self, memory_path):
        if not memory_path or not os.path.exists(memory_path):
            return []

        found = []
        seen = set()
        try:
            with open(memory_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "sub_agent_started" not in line:
                        continue
                    payload = self._parse_first_json_object(line)
                    if not isinstance(payload, dict) or payload.get("event") != "sub_agent_started":
                        continue
                    name = str(payload.get("name") or "").strip()
                    task = str(payload.get("task") or "").strip()
                    key = (name, task)
                    if key in seen:
                        continue
                    seen.add(key)
                    found.append({"name": name, "task": task})
        except Exception:
            return []

        return found

    def list_runs(self):
        self.cleanup_finished()
        with self._lock:
            items = []
            for tid, info in self._history.items():
                items.append(self._run_info_to_public(tid, info))
            for tid, info in self._tasks.items():
                items.append(self._run_info_to_public(tid, info))
        items.sort(key=lambda x: x.get("task_id") or 0)
        return items

    def get_run(self, task_id):
        self.cleanup_finished()
        with self._lock:
            info = self._tasks.get(task_id) or self._history.get(task_id)
            if not info:
                return None
            return self._run_info_to_public(task_id, info)

    def refresh_run_status(self, task_id: int):
        with self._lock:
            info = self._tasks.get(task_id)
            if not info:
                return
            proc = info.get("process")
            if proc is None:
                return
            try:
                alive = bool(proc.is_alive())
            except Exception:
                alive = False

            if alive:
                return

            try:
                proc.join(timeout=0)
            except Exception:
                pass
            info["exitcode"] = getattr(proc, "exitcode", None)
            info["finished_at"] = info.get("finished_at") or datetime.now()
            self._history[task_id] = info
            self._tasks.pop(task_id, None)

    def get_run_memory_path(self, task_id):
        with self._lock:
            info = self._tasks.get(task_id) or self._history.get(task_id)
            if not info:
                return None
            return info.get("memory_path")

    def parse_subagent_events(self, leader_memory_path):
        if not leader_memory_path or not os.path.exists(leader_memory_path):
            return {}

        agents = {}
        try:
            with open(leader_memory_path, "r", encoding="utf-8") as f:
                for line in f:
                    if "sub_agent_" not in line:
                        continue
                    payload = self._parse_first_json_object(line)
                    if not isinstance(payload, dict):
                        continue
                    event = payload.get("event")
                    name = payload.get("name")
                    if not isinstance(name, str) or not name:
                        continue
                    if event == "sub_agent_started":
                        agents[name] = {
                            "name": name,
                            "status": "running",
                            "provider_id": payload.get("provider_id"),
                            "memory_file_path": payload.get("memory_file_path"),
                            "task": payload.get("task"),
                            "leader_task": payload.get("leader_task"),
                            "pid": payload.get("pid"),
                            "exitcode": None,
                            "error": None,
                        }
                    elif event == "sub_agent_finished":
                        prev = agents.get(name) or {}
                        agents[name] = {
                            "name": name,
                            "status": "finished",
                            "provider_id": payload.get("provider_id") or prev.get("provider_id"),
                            "memory_file_path": payload.get("memory_file_path") or prev.get("memory_file_path"),
                            "task": payload.get("task") or prev.get("task"),
                            "leader_task": payload.get("leader_task") or prev.get("leader_task"),
                            "pid": payload.get("pid") or prev.get("pid"),
                            "exitcode": payload.get("exitcode"),
                            "error": payload.get("error"),
                        }
        except Exception:
            return {}

        return agents

    def _run_info_to_public(self, task_id, info):
        proc = info.get("process")
        alive = False
        if proc is not None:
            try:
                alive = bool(proc.is_alive())
            except Exception:
                alive = False
        started_at = info.get("started_at")
        finished_at = info.get("finished_at")
        exitcode = info.get("exitcode")
        if proc is not None:
            try:
                exitcode = proc.exitcode
            except Exception:
                pass
        return {
            "task_id": int(task_id),
            "pid": info.get("pid"),
            "task": info.get("task"),
            "memory_path": info.get("memory_path"),
            "status": "running" if alive else "finished",
            "started_at": started_at.isoformat() if isinstance(started_at, datetime) else None,
            "finished_at": finished_at.isoformat() if isinstance(finished_at, datetime) else None,
            "exitcode": exitcode,
        }

    def state_text(self):
        self.cleanup_finished()
        items = []
        for task_id in sorted(self._tasks.keys()):
            info = self._tasks[task_id]
            proc = info["process"]
            if not proc.is_alive():
                continue
            leader_task = info.get("task") or ""
            items.append(f"LeaderAgent:{leader_task}")
        return "\n".join(items).strip()
