import json


class LeaderDecisionEngine:
    def __init__(self, agent, utils):
        self._agent = agent
        self._utils = utils

    def decide_next(
        self,
        user_task,
        finished_spec,
        finished_output,
        results_by_agent,
        pending_specs,
        running_agent_names=None,
        agents_state=None,
        used_agent_names=None,
    ):
        prompt = self._build_decision_prompt(
            user_task,
            finished_spec,
            finished_output,
            results_by_agent,
            pending_specs,
            running_agent_names=running_agent_names,
            agents_state=agents_state,
            used_agent_names=used_agent_names,
        )

        previous_messages = list(self._agent.messages)
        try:
            self._agent.messages = []
            self._agent.Message("user", prompt)
            raw = self._agent.Send(run_tools=False) if "run_tools" in self._agent.Send.__code__.co_varnames else self._agent.Send()
        except Exception as e:
            decision = {"status": "wait", "error": f"{type(e).__name__}: {e}"}
            self._agent.messages = previous_messages
            self._agent.Message(
                "assistant",
                json.dumps({"event": "leader_decision", "decision": decision, "raw": None}, ensure_ascii=False),
            )
            return decision
        finally:
            self._agent.messages = previous_messages

        if not isinstance(raw, str):
            raw = str(raw)

        parsed = self._utils.parse_first_json_object(raw)
        raw_trimmed = (raw[:2000] + "…") if isinstance(raw, str) and len(raw) > 2000 else raw
        if not isinstance(parsed, dict) or parsed.get("status") not in ("done", "continue", "wait"):
            self._agent.Message(
                "assistant",
                json.dumps({"event": "leader_decision", "decision": None, "raw": raw_trimmed}, ensure_ascii=False),
            )
            return None

        self._agent.Message(
            "assistant",
            json.dumps({"event": "leader_decision", "decision": parsed, "raw": raw_trimmed}, ensure_ascii=False),
        )
        return parsed

    def decide_batch(self, user_task, results_by_agent, agents_state, used_agent_names):
        prompt = self._build_batch_decision_prompt(user_task, results_by_agent, agents_state, used_agent_names)

        previous_messages = list(self._agent.messages)
        try:
            self._agent.messages = []
            self._agent.Message("user", prompt)
            raw = self._agent.Send(run_tools=False) if "run_tools" in self._agent.Send.__code__.co_varnames else self._agent.Send()
        except Exception as e:
            decision = {"status": "wait", "error": f"{type(e).__name__}: {e}"}
            self._agent.messages = previous_messages
            self._agent.Message(
                "assistant",
                json.dumps(
                    {"event": "leader_decision", "mode": "batch", "decision": decision, "raw": None},
                    ensure_ascii=False,
                ),
            )
            return decision
        finally:
            self._agent.messages = previous_messages

        if not isinstance(raw, str):
            raw = str(raw)

        parsed = self._utils.parse_first_json_object(raw)
        raw_trimmed = (raw[:2000] + "…") if isinstance(raw, str) and len(raw) > 2000 else raw
        if not isinstance(parsed, dict) or parsed.get("status") not in ("done", "continue", "wait"):
            self._agent.Message(
                "assistant",
                json.dumps(
                    {"event": "leader_decision", "mode": "batch", "decision": None, "raw": raw_trimmed},
                    ensure_ascii=False,
                ),
            )
            return None

        self._agent.Message(
            "assistant",
            json.dumps(
                {"event": "leader_decision", "mode": "batch", "decision": parsed, "raw": raw_trimmed},
                ensure_ascii=False,
            ),
        )
        return parsed

    def _build_batch_decision_prompt(self, user_task, results_by_agent, agents_state, used_agent_names):
        state_agents = []
        if isinstance(agents_state, dict):
            for _, v in agents_state.items():
                if isinstance(v, dict) and v.get("name"):
                    state_agents.append(v)
        state_agents.sort(key=lambda x: str(x.get("name")))

        used_list = []
        if isinstance(used_agent_names, (set, list, tuple)):
            used_list = [str(x) for x in used_agent_names if x is not None]
            used_list.sort()

        state = {"agents": state_agents, "used_agent_names": used_list, "results_by_agent": results_by_agent}

        return (
            "You are the lead. Wait until all currently scheduled sub-agents have finished, then decide whether the overall task can be finished or whether you need to split and dispatch new sub-agents.\n"
            "Output JSON only. Do not output code fences. Do not output explanations.\n"
            "If you choose to continue, do NOT create an agent name that appears in used_agent_names.\n\n"
            f"Original Task: {user_task}\n\n"
            f"Current State:\n{json.dumps(state, ensure_ascii=False, indent=2)}\n\n"
            "Output format (choose one):\n"
            "1) Task completed:\n"
            '{ "status": "done", "final": "Final deliverable text" }\n'
            "2) Need to continue splitting:\n"
            '{ "status": "continue", "agents": [ {"name": "AgentX", "task": "New subtask", "provider_id": "gemini(optional)"} ] }\n'
            "3) Wait (need more information / cannot proceed now):\n"
            '{ "status": "wait" }\n'
        )

    def _build_decision_prompt(
        self,
        user_task,
        finished_spec,
        finished_output,
        results_by_agent,
        pending_specs,
        running_agent_names=None,
        agents_state=None,
        used_agent_names=None,
    ):
        running_names = []
        if isinstance(running_agent_names, (list, tuple, set)):
            running_names = [str(x) for x in running_agent_names if x is not None]

        state_agents = []
        if isinstance(agents_state, dict):
            for _, v in agents_state.items():
                if isinstance(v, dict) and v.get("name"):
                    state_agents.append(v)
        state_agents.sort(key=lambda x: str(x.get("name")))

        used_list = []
        if isinstance(used_agent_names, (set, list, tuple)):
            used_list = [str(x) for x in used_agent_names if x is not None]
            used_list.sort()

        state = {
            "finished": {"name": finished_spec.get("name"), "task": finished_spec.get("task"), "output": finished_output},
            "results_by_agent": results_by_agent,
            "agents": state_agents,
            "used_agent_names": used_list,
            "running_agents_count": len(running_names),
            "running_agents": running_names,
            "pending_agents_count": len(pending_specs),
        }

        return (
            "You are the lead. After each sub-agent finishes, decide whether the overall task can be finished or whether you need to split and dispatch new sub-agents.\n"
            "Output JSON only. Do not output code fences. Do not output explanations.\n\n"
            f"Original Task: {user_task}\n\n"
            f"Current State:\n{json.dumps(state, ensure_ascii=False, indent=2)}\n\n"
            "Output format (choose one):\n"
            "1) Task completed:\n"  
            '{ "status": "done", "final": "Final deliverable text" }\n'
            "2) Need to continue splitting:\n"
            '{ "status": "continue", "agents": [ {"name": "AgentX", "task": "New subtask", "provider_id": "gemini(optional)"} ] }\n'
            "3) Wait for current running sub-agents:\n"
            '{ "status": "wait" }\n'
        )
