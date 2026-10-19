"""WorkBuddy's catalog-driven Chat Completions contract on the shared tool loop."""
from src.workbuddy.gateway import WorkBuddyGateway, WorkBuddyError
from .openai_agent import OpenAIAgent
from .openai_chat_runtime import OpenAIChatRuntime


class WorkBuddyChatRuntime(OpenAIChatRuntime):
    def _build_chat_payload(self, *, messages, active_tools, reasoning_effort, thinking_mode, stream):
        catalog = WorkBuddyGateway(self.config).catalog()
        model = next((item for item in catalog.data if item.id == self.config["model"]), None)
        if model is None:
            raise WorkBuddyError("所选模型不在当前 WorkBuddy 账号目录中，请刷新模型列表。")
        if not model.supportsImages:
            for message in messages:
                content = message.get("content")
                if isinstance(content, list) and any(item.get("type") == "image_url" for item in content):
                    raise WorkBuddyError("所选 WorkBuddy 模型不支持图片输入。")
        payload = super()._build_chat_payload(messages=messages, active_tools=active_tools,
            reasoning_effort=None, thinking_mode="disabled", stream=stream)
        payload["max_tokens"] = model.maxTokens
        if thinking_mode in {"enabled", "auto"}:
            effort = str(reasoning_effort or "")
            if not model.reasoningEfforts:
                raise WorkBuddyError("所选 WorkBuddy 模型未声明思考能力。")
            if effort:
                if effort not in model.reasoningEfforts:
                    raise WorkBuddyError("所选 WorkBuddy 模型不支持此思考强度，请检查模型目录。")
                payload["reasoning_effort"] = effort
        return payload


class WorkBuddyAgent(OpenAIAgent):
    def _create_chat_runtime(self):
        return WorkBuddyChatRuntime(self)
