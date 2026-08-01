from __future__ import annotations

from typing import Any

from src.runtime_policy import bound_runtime_policy_for_agent
from src.runtime_policy.contracts import ImplementationCheckpointPolicy


class ResponsesImplementationCheckpoint:
    def __init__(self, *, policy: ImplementationCheckpointPolicy | None) -> None:
        self.policy = policy
        self.evidence_operations = 0
        self.started = False
        self.patch_seen = False
        self._instruction_message: dict[str, Any] | None = None

    @classmethod
    def from_agent(cls, agent: object) -> "ResponsesImplementationCheckpoint":
        resolved = bound_runtime_policy_for_agent(agent)
        return cls(
            policy=resolved.policy.implementation_checkpoint if resolved is not None else None
        )

    def observe(
        self,
        runtime: object,
        *,
        function_calls: object,
        executions: object,
    ) -> bool:
        if self.policy is None or not self.policy.enabled or self.started or self.patch_seen:
            return False

        calls_by_id = {
            str(getattr(call, "call_id", "") or ""): call
            for call in function_calls if isinstance(function_calls, list)
        }
        for execution in executions if isinstance(executions, list) else []:
            if str(getattr(execution, "status", "") or "").strip().lower() != "completed":
                continue
            call = calls_by_id.get(str(getattr(execution, "call_id", "") or ""))
            if call is None:
                continue
            if self._contains_patch(call):
                self.patch_seen = True
                return False
            self.evidence_operations += self._evidence_operation_count(call)

        if self.evidence_operations < self.policy.evidence_operation_limit:
            return False

        messages = getattr(runtime, "messages", None)
        instruction_factory = getattr(runtime, "RuntimeInstructionMessage", None)
        if not isinstance(messages, list) or not callable(instruction_factory):
            raise TypeError(
                "Responses implementation checkpoint requires an agent message list and instruction policy."
            )
        self.started = True
        self._instruction_message = instruction_factory(self.policy.prompt)
        messages.append(self._instruction_message)
        return True

    def start_phase(self, runtime: object) -> None:
        self.finish(runtime)
        self.evidence_operations = 0
        self.started = False
        self.patch_seen = False

    def finish(self, runtime: object) -> None:
        messages = getattr(runtime, "messages", None)
        if isinstance(messages, list) and isinstance(self._instruction_message, dict):
            instruction_id = id(self._instruction_message)
            messages[:] = [message for message in messages if id(message) != instruction_id]
        self._instruction_message = None

    def _contains_patch(self, call: object) -> bool:
        name = str(getattr(call, "name", "") or "").strip()
        if name in self.policy.patch_tools:
            return True
        if name != self.policy.workspace_tool:
            return False
        return any(
            str(operation.get("kind") or "").strip() in self.policy.workspace_patch_kinds
            for operation in _workspace_operations(call)
        )

    def _evidence_operation_count(self, call: object) -> int:
        name = str(getattr(call, "name", "") or "").strip()
        if name in self.policy.direct_evidence_tools:
            return 1
        if name != self.policy.workspace_tool:
            return 0
        return sum(
            str(operation.get("kind") or "").strip() in self.policy.workspace_evidence_kinds
            for operation in _workspace_operations(call)
        )


def _workspace_operations(call: object) -> list[dict[str, Any]]:
    arguments = getattr(call, "arguments", None)
    stages = arguments.get("stages") if isinstance(arguments, dict) else None
    operations: list[dict[str, Any]] = []
    for stage in stages if isinstance(stages, list) else []:
        stage_operations = stage.get("operations") if isinstance(stage, dict) else None
        operations.extend(
            operation
            for operation in stage_operations if isinstance(stage_operations, list)
            if isinstance(operation, dict)
        )
    return operations


__all__ = ["ResponsesImplementationCheckpoint"]
