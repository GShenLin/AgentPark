import json
import multiprocessing as mp
import queue
import time


class ProcessIterativeDispatchRunner:
    def __init__(self, agent, spawner, planner, decider, utils):
        self._agent = agent
        self._spawner = spawner
        self._planner = planner
        self._decider = decider
        self._utils = utils

    def run_iterative_dispatch(self, user_task, planned_specs, base_dir, max_concurrency=None, max_total_agents=None, max_decisions=24):
        ctx = mp.get_context("spawn")
        result_queue = ctx.Queue()

        has_total_limit = isinstance(max_total_agents, int) and max_total_agents > 0
        used_names = {s.get("name") for s in planned_specs if isinstance(s, dict) and isinstance(s.get("name"), str)}

        pending = list(planned_specs or [])
        running = {}
        results_by_agent = {}
        agents_state = {}
        decisions_used = 0
        final_answer = None

        max_workers = max(1, len(pending) or 1)
        if isinstance(max_concurrency, int) and max_concurrency > 0:
            max_workers = max(1, min(max_workers, max_concurrency))

        for spec in pending:
            name = spec.get("name") if isinstance(spec, dict) else None
            if not isinstance(name, str) or not name:
                continue
            agents_state[name] = {
                "name": name,
                "status": "pending",
                "provider_id": spec.get("provider_id") or self._agent.provider_name,
                "memory_file_path": spec.get("memory_file_path") or self._utils.build_agent_memory_path(name, base_dir),
                "task": spec.get("task"),
                "pid": None,
                "exitcode": None,
                "error": None,
                "output_preview": None,
            }

        def schedule_more():
            while pending and len(running) < max_workers and (not has_total_limit or len(used_names) < max_total_agents):
                spec = pending.pop(0)
                if not isinstance(spec, dict):
                    continue
                name = spec.get("name")
                task = spec.get("task")
                memory_file_path = spec.get("memory_file_path") or self._utils.build_agent_memory_path(name, base_dir)
                provider_id = spec.get("provider_id")
                handle = self._spawner.create_sub_agent(
                    name,
                    memory_file_path,
                    provider_id=provider_id,
                    task=task,
                    leader_task=user_task,
                    result_queue=result_queue,
                )
                running[name] = (handle.process, {**spec, "provider_id": handle.provider_id, "memory_file_path": memory_file_path})
                agents_state[name] = {
                    "name": name,
                    "status": "running",
                    "provider_id": handle.provider_id,
                    "memory_file_path": memory_file_path,
                    "task": task,
                    "pid": handle.process.pid,
                    "exitcode": None,
                    "error": None,
                    "output_preview": None,
                }

        while True:
            if not running and not pending:
                break

            schedule_more()
            last_activity = time.time()

            while running:
                try:
                    msg = result_queue.get(timeout=1.0)
                    last_activity = time.time()
                except queue.Empty:
                    msg = None

                if isinstance(msg, dict) and msg.get("event") == "sub_agent_finished":
                    name = msg.get("name")
                    proc, spec = running.pop(name, (None, None))
                    if proc is not None:
                        proc.join(timeout=5)

                    output = msg.get("output")
                    if not isinstance(output, str):
                        output = str(output)
                    results_by_agent[name] = output

                    if isinstance(name, str) and name:
                        agents_state[name] = {
                            "name": name,
                            "status": "finished",
                            "provider_id": msg.get("provider_id") or (spec or {}).get("provider_id") or self._agent.provider_name,
                            "memory_file_path": msg.get("memory_file_path") or (spec or {}).get("memory_file_path"),
                            "task": msg.get("task") or (spec or {}).get("task"),
                            "pid": msg.get("pid") or (proc.pid if proc is not None else None),
                            "exitcode": proc.exitcode if proc is not None else None,
                            "error": msg.get("error"),
                            "output_preview": (output[:800] + "…") if isinstance(output, str) and len(output) > 800 else output,
                        }

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

                    schedule_more()
                    continue

                dead = []
                for name, (proc, spec) in running.items():
                    if not proc.is_alive():
                        dead.append((name, proc, spec))

                for name, proc, spec in dead:
                    running.pop(name, None)
                    proc.join(timeout=0)
                    output = f"Error: process exited with code {proc.exitcode}"
                    results_by_agent[name] = output
                    agents_state[name] = {
                        "name": name,
                        "status": "finished",
                        "provider_id": (spec or {}).get("provider_id") or self._agent.provider_name,
                        "memory_file_path": (spec or {}).get("memory_file_path"),
                        "task": (spec or {}).get("task"),
                        "pid": proc.pid,
                        "exitcode": proc.exitcode,
                        "error": output,
                        "output_preview": output,
                    }
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
                    schedule_more()
                    continue

                if (time.time() - last_activity) > 600:
                    for name, (proc, spec) in list(running.items()):
                        if proc.is_alive():
                            proc.terminate()
                            proc.join(timeout=5)
                        output = "Error: timeout"
                        results_by_agent[name] = output
                        agents_state[name] = {
                            "name": name,
                            "status": "finished",
                            "provider_id": (spec or {}).get("provider_id") or self._agent.provider_name,
                            "memory_file_path": (spec or {}).get("memory_file_path"),
                            "task": (spec or {}).get("task"),
                            "pid": proc.pid,
                            "exitcode": proc.exitcode,
                            "error": output,
                            "output_preview": output,
                        }
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

            if pending:
                continue

            if final_answer is None and decisions_used < max_decisions:
                try:
                    decision = self._decider.decide_batch(user_task, results_by_agent, agents_state, used_names)
                except Exception as e:
                    decision = {"status": "wait", "error": f"{type(e).__name__}: {e}"}

                decisions_used += 1

                if isinstance(decision, dict):
                    status = decision.get("status")
                    if status == "done":
                        final_answer = decision.get("final")
                        break
                    if status == "continue":
                        new_agents = self._planner.normalize_planned_agents(decision, base_dir=base_dir)
                        for a in new_agents:
                            if has_total_limit and len(used_names) >= max_total_agents:
                                break
                            unique_name = self._utils.unique_agent_name(a["name"], used_names)
                            used_names.add(unique_name)
                            next_spec = {
                                "name": unique_name,
                                "task": a["task"],
                                "provider_id": a.get("provider_id"),
                                "memory_file_path": self._utils.build_agent_memory_path(unique_name, base_dir),
                            }
                            pending.append(next_spec)
                            agents_state[unique_name] = {
                                "name": unique_name,
                                "status": "pending",
                                "provider_id": next_spec.get("provider_id") or self._agent.provider_name,
                                "memory_file_path": next_spec.get("memory_file_path"),
                                "task": next_spec.get("task"),
                                "pid": None,
                                "exitcode": None,
                                "error": None,
                                "output_preview": None,
                            }
                        continue
                    break

            break

        return final_answer, results_by_agent
