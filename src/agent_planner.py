class AgentPlanner:
    def __init__(self, agent, utils):
        self._agent = agent
        self._utils = utils

    def plan_subtasks(self, user_task, agent_names=None):
        task = str(user_task or "").strip()
        return {"steps": [{"name": "Step_1", "task": task}]}

    def normalize_planned_agents(self, plan, base_dir):
        if not isinstance(plan, dict):
            return []

        agents = plan.get("steps")
        if not isinstance(agents, list):
            agents = plan.get("agents")
        normalized = []

        if isinstance(agents, list):
            for a in agents:
                if not isinstance(a, dict):
                    continue
                name = a.get("name")
                task = a.get("task")
                if not isinstance(name, str) or not name.strip():
                    continue
                if not isinstance(task, str) or not task.strip():
                    continue
                clean_name = self._utils.sanitize_agent_name(name)
                normalized.append(
                    {
                        "name": clean_name,
                        "task": task.strip(),
                        "provider_id": None,
                        "memory_file_path": None,
                    }
                )

        if normalized:
            return self._utils.dedupe_agents(normalized)

        name_to_task = plan.get("tasks")
        if isinstance(name_to_task, dict):
            for name, task in name_to_task.items():
                if not isinstance(name, str) or not name.strip():
                    continue
                if not isinstance(task, str) or not task.strip():
                    continue
                clean_name = self._utils.sanitize_agent_name(name)
                normalized.append(
                    {
                        "name": clean_name,
                        "task": task.strip(),
                        "provider_id": None,
                        "memory_file_path": None,
                    }
                )

        return self._utils.dedupe_agents(normalized)
