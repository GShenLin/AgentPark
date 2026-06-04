import json
import multiprocessing as mp
import os

from src.sub_agent_process_handle import SubAgentProcessHandle


def run_subagent_task_process(spec, result_queue):
    name = spec.get("name")
    provider_id = spec.get("provider_id")
    memory_file_path = spec.get("memory_file_path")
    task = spec.get("task")
    leader_task = spec.get("leader_task")

    payload = {
        "event": "sub_agent_finished",
        "name": name,
        "provider_id": provider_id,
        "memory_file_path": memory_file_path,
        "task": task,
        "output": None,
        "error": None,
        "pid": os.getpid(),
    }

    try:
        from src.providers import create_agent

        if not memory_file_path:
            raise ValueError("memory_file_path is required when creating a sub-agent")

        sub = create_agent(provider_id, memory_file_path=memory_file_path)
        sub.addTool("system_tools")
        effective_task = task
        if isinstance(leader_task, str) and leader_task.strip():
            if isinstance(task, str) and task.strip():
                effective_task = f"Leader任务：\n{leader_task.strip()}\n\n你的分配任务：\n{task.strip()}"
            else:
                effective_task = f"Leader任务：\n{leader_task.strip()}"
        output = sub.run_task(effective_task, use_preflight=False)
        if not isinstance(output, str):
            output = str(output)
        payload["output"] = output
    except BaseException as e:
        payload["error"] = f"{type(e).__name__}: {e}"
        payload["output"] = payload["error"]
    finally:
        try:
            result_queue.put(payload)
        except Exception:
            pass


class SubAgentSpawner:
    def __init__(self, agent, sub_agents):
        self._agent = agent
        self._sub_agents = sub_agents

    def create_sub_agent(self, agent_name, memory_file_path, provider_id=None, task=None, leader_task=None, result_queue=None):
        actual_provider_id = provider_id or self._agent.provider_name
        print(f"Creating sub-agent: {agent_name} with provider: {actual_provider_id}")
        from src.providers import create_agent

        if not memory_file_path:
            raise ValueError("memory_file_path is required when creating a sub-agent")

        if task is not None:
            ctx = mp.get_context("spawn")
            q = result_queue or ctx.Queue()
            spec = {
                "name": agent_name,
                "provider_id": actual_provider_id,
                "memory_file_path": memory_file_path,
                "task": task,
                "leader_task": leader_task,
            }
            p = ctx.Process(target=run_subagent_task_process, args=(spec, q))
            p.daemon = False
            p.start()
            handle = SubAgentProcessHandle(agent_name, actual_provider_id, memory_file_path, task, p, q)
            self._sub_agents[agent_name] = handle
            self._agent.Message(
                "assistant",
                json.dumps(
                    {
                        "event": "sub_agent_started",
                        "name": agent_name,
                        "provider_id": actual_provider_id,
                        "memory_file_path": memory_file_path,
                        "task": task,
                        "leader_task": leader_task,
                        "pid": p.pid,
                    },
                    ensure_ascii=False,
                ),
            )
            return handle

        sub = create_agent(actual_provider_id, memory_file_path=memory_file_path)
        sub.addTool("system_tools")
        self._sub_agents[agent_name] = sub
        self._agent.Message(
            "assistant",
            json.dumps(
                {"event": "sub_agent_created", "name": agent_name, "provider_id": actual_provider_id, "memory_file_path": memory_file_path},
                ensure_ascii=False,
            ),
        )
        return sub
