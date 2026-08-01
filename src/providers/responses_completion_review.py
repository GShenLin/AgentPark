from __future__ import annotations

from src.task_direction_models import TaskDirectionContractError
from src.task_direction_store import TaskDirectionStore
from src.runtime_policy import bound_runtime_policy_for_agent


class ResponsesCompletionReview:
    def __init__(
        self,
        *,
        enabled: bool,
        max_passes: int,
        require_tool_executions: bool,
        require_done_criteria: bool,
        require_resolved_risks: bool,
        prompt: str,
    ) -> None:
        self.enabled = enabled
        self.max_passes = max_passes
        self.require_tool_executions = require_tool_executions
        self.require_done_criteria = require_done_criteria
        self.require_resolved_risks = require_resolved_risks
        self.prompt = prompt
        self.pass_count = 0
        self._draft_message: dict | None = None
        self._instruction_message: dict | None = None

    @classmethod
    def from_agent(cls, agent: object) -> "ResponsesCompletionReview":
        resolved = bound_runtime_policy_for_agent(agent)
        if resolved is None:
            return cls(
                enabled=False,
                max_passes=1,
                require_tool_executions=True,
                require_done_criteria=False,
                require_resolved_risks=False,
                prompt="",
            )
        policy = resolved.policy.completion_review
        return cls(
            enabled=policy.enabled,
            max_passes=policy.passes,
            require_tool_executions=policy.require_tool_executions,
            require_done_criteria=policy.require_done_criteria,
            require_resolved_risks=policy.require_resolved_risks,
            prompt=policy.prompt,
        )

    def _remove_transient_messages(self, messages: list) -> None:
        review_ids = {
            id(message)
            for message in (self._draft_message, self._instruction_message)
            if isinstance(message, dict)
        }
        if review_ids:
            messages[:] = [message for message in messages if id(message) not in review_ids]

    def start_if_needed(
        self,
        runtime: object,
        *,
        draft_text: object,
        had_regular_tool_executions: bool,
    ) -> bool:
        text = str(draft_text or "").strip()
        direction_issues = self._task_direction_issues(runtime)
        if (
            not self.enabled
            or (self.require_tool_executions and not had_regular_tool_executions)
            or not text
        ):
            return False
        needs_initial_review = self.pass_count == 0
        if not needs_initial_review and not direction_issues:
            return False
        if self.pass_count >= self.max_passes:
            return False
        messages = getattr(runtime, "messages", None)
        instruction_factory = getattr(runtime, "RuntimeInstructionMessage", None)
        if not isinstance(messages, list) or not callable(instruction_factory):
            raise TypeError("Responses completion review requires an agent message list and instruction policy.")

        self._remove_transient_messages(messages)
        self.pass_count += 1
        self._draft_message = {"role": "assistant", "content": text}
        instruction = self.prompt
        if direction_issues:
            instruction += (
                "\n\n[Unclosed Task Direction Contract]\n- "
                + "\n- ".join(direction_issues)
                + "\nUpdate the task-direction ledger with evidence after fixing or "
                "reconciling every item. Do not claim completion while any listed "
                "criterion or risk remains open."
            )
        self._instruction_message = instruction_factory(instruction)
        messages.extend([self._draft_message, self._instruction_message])
        return True

    def _task_direction_issues(self, runtime: object) -> list[str]:
        if not self.require_done_criteria and not self.require_resolved_risks:
            return []
        try:
            stored = TaskDirectionStore.for_agent(runtime).read()
        except TaskDirectionContractError:
            return []
        if stored is None:
            return ["task-direction ledger is missing"]
        issues: list[str] = []
        if self.require_done_criteria:
            issues.extend(
                f"criterion {item.id} is {item.status}: {item.statement}"
                for item in stored.state.done_criteria
                if item.status != "met"
            )
        if self.require_resolved_risks:
            issues.extend(
                f"risk {item.id} is {item.status}: {item.statement}"
                for item in stored.state.unresolved_risks
                if item.status != "resolved"
            )
        return issues

    def finish(self, runtime: object) -> None:
        if self.pass_count == 0:
            return
        messages = getattr(runtime, "messages", None)
        if isinstance(messages, list):
            self._remove_transient_messages(messages)
        self._draft_message = None
        self._instruction_message = None


__all__ = ["ResponsesCompletionReview"]
