from __future__ import annotations

from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from src.runtime_policy.context_compaction import ContextCompactionPolicy


class RuntimePolicyValidationError(ValueError):
    pass


@dataclass(frozen=True)
class TaskDirectionPolicy:
    enabled: bool
    required_tools: tuple[str, ...]
    analysis_tools: tuple[str, ...]
    core_prompt: str
    code_prompt: str

    @classmethod
    def from_payload(cls, payload: object, *, field: str) -> "TaskDirectionPolicy":
        data = _strict_object(
            payload,
            field=field,
            required={
                "enabled",
                "required_tools",
                "analysis_tools",
                "core_prompt",
                "code_prompt",
            },
        )
        return cls(
            enabled=_boolean(data["enabled"], field=f"{field}.enabled"),
            required_tools=_string_tuple(data["required_tools"], field=f"{field}.required_tools"),
            analysis_tools=_string_tuple(data["analysis_tools"], field=f"{field}.analysis_tools"),
            core_prompt=_prompt(data["core_prompt"], field=f"{field}.core_prompt"),
            code_prompt=_prompt(data["code_prompt"], field=f"{field}.code_prompt"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "required_tools": list(self.required_tools),
            "analysis_tools": list(self.analysis_tools),
            "core_prompt": self.core_prompt,
            "code_prompt": self.code_prompt,
        }


@dataclass(frozen=True)
class CompletionReviewPolicy:
    enabled: bool
    passes: int
    require_tool_executions: bool
    require_done_criteria: bool
    require_resolved_risks: bool
    prompt: str

    @classmethod
    def from_payload(cls, payload: object, *, field: str) -> "CompletionReviewPolicy":
        data = _strict_object(
            payload,
            field=field,
            required={
                "enabled",
                "passes",
                "require_tool_executions",
                "require_done_criteria",
                "require_resolved_risks",
                "prompt",
            },
        )
        return cls(
            enabled=_boolean(data["enabled"], field=f"{field}.enabled"),
            passes=_integer(data["passes"], field=f"{field}.passes", minimum=1, maximum=5),
            require_tool_executions=_boolean(
                data["require_tool_executions"],
                field=f"{field}.require_tool_executions",
            ),
            require_done_criteria=_boolean(
                data["require_done_criteria"],
                field=f"{field}.require_done_criteria",
            ),
            require_resolved_risks=_boolean(
                data["require_resolved_risks"],
                field=f"{field}.require_resolved_risks",
            ),
            prompt=_prompt(data["prompt"], field=f"{field}.prompt"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "passes": self.passes,
            "require_tool_executions": self.require_tool_executions,
            "require_done_criteria": self.require_done_criteria,
            "require_resolved_risks": self.require_resolved_risks,
            "prompt": self.prompt,
        }


@dataclass(frozen=True)
class ImplementationCheckpointPolicy:
    enabled: bool
    evidence_operation_limit: int
    workspace_tool: str
    direct_evidence_tools: tuple[str, ...]
    workspace_evidence_kinds: tuple[str, ...]
    patch_tools: tuple[str, ...]
    workspace_patch_kinds: tuple[str, ...]
    prompt: str

    @classmethod
    def from_payload(
        cls,
        payload: object,
        *,
        field: str,
    ) -> "ImplementationCheckpointPolicy":
        data = _strict_object(
            payload,
            field=field,
            required={
                "enabled",
                "evidence_operation_limit",
                "workspace_tool",
                "direct_evidence_tools",
                "workspace_evidence_kinds",
                "patch_tools",
                "workspace_patch_kinds",
                "prompt",
            },
        )
        return cls(
            enabled=_boolean(data["enabled"], field=f"{field}.enabled"),
            evidence_operation_limit=_integer(
                data["evidence_operation_limit"],
                field=f"{field}.evidence_operation_limit",
                minimum=1,
                maximum=1000,
            ),
            workspace_tool=_non_empty_string(
                data["workspace_tool"],
                field=f"{field}.workspace_tool",
            ),
            direct_evidence_tools=_string_tuple(
                data["direct_evidence_tools"],
                field=f"{field}.direct_evidence_tools",
            ),
            workspace_evidence_kinds=_string_tuple(
                data["workspace_evidence_kinds"],
                field=f"{field}.workspace_evidence_kinds",
            ),
            patch_tools=_string_tuple(data["patch_tools"], field=f"{field}.patch_tools"),
            workspace_patch_kinds=_string_tuple(
                data["workspace_patch_kinds"],
                field=f"{field}.workspace_patch_kinds",
            ),
            prompt=_prompt(data["prompt"], field=f"{field}.prompt"),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "evidence_operation_limit": self.evidence_operation_limit,
            "workspace_tool": self.workspace_tool,
            "direct_evidence_tools": list(self.direct_evidence_tools),
            "workspace_evidence_kinds": list(self.workspace_evidence_kinds),
            "patch_tools": list(self.patch_tools),
            "workspace_patch_kinds": list(self.workspace_patch_kinds),
            "prompt": self.prompt,
        }


@dataclass(frozen=True)
class CodingRuntimePolicy:
    schema_version: int
    policy_id: str
    version: str
    description: str
    task_direction: TaskDirectionPolicy
    completion_review: CompletionReviewPolicy
    implementation_checkpoint: ImplementationCheckpointPolicy
    context_compaction: "ContextCompactionPolicy"

    @classmethod
    def from_payload(cls, payload: object, *, field: str = "runtime_policy") -> "CodingRuntimePolicy":
        data = _strict_object(
            payload,
            field=field,
            required={
                "schema_version",
                "policy_id",
                "version",
                "description",
                "task_direction",
                "completion_review",
                "implementation_checkpoint",
                "context_compaction",
            },
        )
        schema_version = _integer(
            data["schema_version"],
            field=f"{field}.schema_version",
            minimum=1,
            maximum=1,
        )
        from src.runtime_policy.context_compaction import ContextCompactionPolicy

        return cls(
            schema_version=schema_version,
            policy_id=_identifier(data["policy_id"], field=f"{field}.policy_id"),
            version=_non_empty_string(data["version"], field=f"{field}.version"),
            description=_string(data["description"], field=f"{field}.description"),
            task_direction=TaskDirectionPolicy.from_payload(
                data["task_direction"],
                field=f"{field}.task_direction",
            ),
            completion_review=CompletionReviewPolicy.from_payload(
                data["completion_review"],
                field=f"{field}.completion_review",
            ),
            implementation_checkpoint=ImplementationCheckpointPolicy.from_payload(
                data["implementation_checkpoint"],
                field=f"{field}.implementation_checkpoint",
            ),
            context_compaction=ContextCompactionPolicy.from_payload(
                data["context_compaction"],
                field=f"{field}.context_compaction",
            ),
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "version": self.version,
            "description": self.description,
            "task_direction": self.task_direction.to_payload(),
            "completion_review": self.completion_review.to_payload(),
            "implementation_checkpoint": self.implementation_checkpoint.to_payload(),
            "context_compaction": self.context_compaction.to_payload(),
        }


def _strict_object(
    payload: object,
    *,
    field: str,
    required: set[str],
    optional: set[str] | None = None,
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise RuntimePolicyValidationError(f"{field} must be an object.")
    allowed = required | (optional or set())
    missing = sorted(required - set(payload))
    if missing:
        raise RuntimePolicyValidationError(f"{field} is missing required fields: {', '.join(missing)}.")
    unknown = sorted(set(payload) - allowed)
    if unknown:
        raise RuntimePolicyValidationError(f"{field} has unknown fields: {', '.join(unknown)}.")
    return dict(payload)


def _boolean(value: object, *, field: str) -> bool:
    if not isinstance(value, bool):
        raise RuntimePolicyValidationError(f"{field} must be a boolean.")
    return value


def _integer(value: object, *, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise RuntimePolicyValidationError(f"{field} must be an integer.")
    if value < minimum or value > maximum:
        raise RuntimePolicyValidationError(f"{field} must be between {minimum} and {maximum}.")
    return value


def _string(value: object, *, field: str) -> str:
    if not isinstance(value, str):
        raise RuntimePolicyValidationError(f"{field} must be a string.")
    return value


def _non_empty_string(value: object, *, field: str) -> str:
    text = _string(value, field=field).strip()
    if not text:
        raise RuntimePolicyValidationError(f"{field} must not be empty.")
    return text


def _identifier(value: object, *, field: str) -> str:
    text = _non_empty_string(value, field=field)
    if any(not (char.isalnum() or char in {"-", "_", "."}) for char in text):
        raise RuntimePolicyValidationError(
            f"{field} may contain only letters, digits, '.', '_' and '-'."
        )
    return text


def _prompt(value: object, *, field: str) -> str:
    return _non_empty_string(value, field=field)


def _string_tuple(value: object, *, field: str) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise RuntimePolicyValidationError(f"{field} must be an array of strings.")
    items: list[str] = []
    for index, item in enumerate(value):
        text = _non_empty_string(item, field=f"{field}[{index}]")
        if text in items:
            raise RuntimePolicyValidationError(f"{field} contains duplicate value {text!r}.")
        items.append(text)
    return tuple(items)


__all__ = [
    "CodingRuntimePolicy",
    "CompletionReviewPolicy",
    "ImplementationCheckpointPolicy",
    "RuntimePolicyValidationError",
    "TaskDirectionPolicy",
]
