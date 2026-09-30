import json

from src.providers.agent_config import AgentSendContext
from src.providers.agent_invocation import send_agent


class BaseAgentManager:
    def __init__(self, agent):
        self.agent = agent

    def passWork(self, agent, task):
        agent.Message("user", task)

    def finishWork(self):
        return list(self.agent.messages)

    def makePlan(self, user_task):
        try:
            self.agent.Message("assistant", json.dumps({"event": "execution_mode", "mode": "single_agent"}, ensure_ascii=False))
        except Exception:
            pass
        task = str(user_task or "").strip()
        if not task:
            return ""
        self.agent.Message("user", task)
        output = self._send_with_optional_kwargs(run_tools=True)
        if not isinstance(output, str):
            output = str(output)
        return output

    def _send_with_optional_kwargs(self, run_tools=None):
        return send_agent(self.agent, AgentSendContext(run_tools=run_tools))

