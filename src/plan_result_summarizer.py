import json


class PlanResultSummarizer:
    def __init__(self, agent):
        self._agent = agent

    def summarize(self, user_task, results_by_agent):
        prompt = (
            "You are the lead. Produce a final consolidated summary based on the task and the outputs from all agents."
            "Requirements: clear structure, avoid repetition, and explicitly call out uncertainties.\n\n"
            f"Original Task: {user_task}\n\n"
            f"Agent Outputs:\n{json.dumps(results_by_agent, ensure_ascii=False, indent=2)}\n"
        )

        previous_messages = list(self._agent.messages)
        try:
            self._agent.messages = []
            self._agent.Message("user", prompt)
            final = self._agent.Send(run_tools=False) if "run_tools" in self._agent.Send.__code__.co_varnames else self._agent.Send()
        except Exception:
            final = None
        finally:
            self._agent.messages = previous_messages

        if isinstance(final, str) and final.strip():
            return final

        lines = [f"原始任务：{user_task}", "汇总："]
        if isinstance(results_by_agent, dict):
            for name, out in results_by_agent.items():
                lines.append(f"\n[{name}]\n{out}")
        return "\n".join(lines)
