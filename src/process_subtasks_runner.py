import json
import multiprocessing as mp
import queue
import time


class ProcessSubtasksRunner:
    def __init__(self, agent, spawner):
        self._agent = agent
        self._spawner = spawner

    def run_subtasks(self, planned_specs, leader_task=None, max_concurrency=None):
        specs = [s for s in (planned_specs or []) if isinstance(s, dict)]
        if not specs:
            return {}

        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()

        max_workers = len(specs)
        if isinstance(max_concurrency, int) and max_concurrency > 0:
            max_workers = max(1, min(max_workers, max_concurrency))

        pending = list(specs)
        running = {}
        results_by_agent = {}

        def start_one(spec):
            name = spec.get("name")
            task = spec.get("task")
            memory_file_path = spec.get("memory_file_path")
            provider_id = spec.get("provider_id") or self._agent.provider_name
            handle = self._spawner.create_sub_agent(
                name,
                memory_file_path,
                provider_id=provider_id,
                task=task,
                leader_task=leader_task,
                result_queue=result_queue,
            )
            running[name] = (handle.process, spec)

        while pending and len(running) < max_workers:
            start_one(pending.pop(0))

        last_activity = time.time()

        while running:
            try:
                msg = result_queue.get(timeout=1.0)
                last_activity = time.time()
            except queue.Empty:
                msg = None

            if isinstance(msg, dict) and msg.get("event") == "sub_agent_finished":
                name = msg.get("name")
                spec = None
                proc = None
                if name in running:
                    proc, spec = running.pop(name)
                if proc is not None:
                    proc.join(timeout=5)

                output = msg.get("output")
                if not isinstance(output, str):
                    output = str(output)
                results_by_agent[name] = output

                self._agent.Message(
                    "assistant",
                    json.dumps(
                        {
                            "event": "sub_agent_finished",
                            "name": name,
                            "provider_id": msg.get("provider_id"),
                            "memory_file_path": msg.get("memory_file_path"),
                            "task": msg.get("task"),
                            "pid": msg.get("pid"),
                        },
                        ensure_ascii=False,
                    ),
                )

                while pending and len(running) < max_workers:
                    start_one(pending.pop(0))

                continue

            dead = []
            for name, (proc, spec) in running.items():
                if not proc.is_alive():
                    dead.append((name, proc, spec))
            for name, proc, spec in dead:
                running.pop(name, None)
                proc.join(timeout=0)
                results_by_agent[name] = f"Error: process exited with code {proc.exitcode}"
                self._agent.Message(
                    "assistant",
                    json.dumps(
                        {
                            "event": "sub_agent_finished",
                            "name": name,
                            "provider_id": (spec or {}).get("provider_id"),
                            "memory_file_path": (spec or {}).get("memory_file_path"),
                            "task": (spec or {}).get("task"),
                            "pid": proc.pid,
                            "exitcode": proc.exitcode,
                        },
                        ensure_ascii=False,
                    ),
                )

            if dead:
                while pending and len(running) < max_workers:
                    start_one(pending.pop(0))
                continue

            if (time.time() - last_activity) > 600:
                for name, (proc, spec) in list(running.items()):
                    if proc.is_alive():
                        proc.terminate()
                        proc.join(timeout=5)
                    results_by_agent[name] = "Error: timeout"
                    self._agent.Message(
                        "assistant",
                        json.dumps(
                            {
                                "event": "sub_agent_finished",
                                "name": name,
                                "provider_id": (spec or {}).get("provider_id"),
                                "memory_file_path": (spec or {}).get("memory_file_path"),
                                "task": (spec or {}).get("task"),
                                "pid": proc.pid,
                                "exitcode": proc.exitcode,
                                "timeout": True,
                            },
                            ensure_ascii=False,
                        ),
                    )
                running = {}

        return results_by_agent
