from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
import os
import uuid
from typing import Any

from src.file_transaction import run_with_interprocess_lock


LEDGER_SCHEMA_VERSION = 1
LEDGER_FILENAME = "agent_steps.jsonl"
TOOL_OUTCOME_UNKNOWN = "TOOL_OUTCOME_UNKNOWN"


class AgentStepLedgerError(RuntimeError):
    pass


@dataclass(frozen=True)
class UnknownToolOutcome:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    step_id: str

    def to_payload(self) -> dict[str, Any]:
        return {
            "code": TOOL_OUTCOME_UNKNOWN,
            "call_id": self.call_id,
            "tool": self.tool_name,
            "arguments": dict(self.arguments),
            "step_id": self.step_id,
            "instruction": (
                "The tool started before the previous process stopped, but no durable result was recorded. "
                "Retry only when the operation is read-only or idempotent. For operations with side effects, "
                "verify the external state first or ask the user before retrying."
            ),
        }


class AgentStepLedger:
    def __init__(self, path: str):
        resolved = os.path.abspath(str(path or "").strip()) if str(path or "").strip() else ""
        if not resolved:
            raise AgentStepLedgerError("agent step ledger path is empty")
        self.path = resolved
        self.lock_path = resolved + ".lock"

    def append(self, event_type: str, **data: Any) -> dict[str, Any]:
        resolved_type = str(event_type or "").strip()
        if not resolved_type:
            raise AgentStepLedgerError("agent step event type is empty")

        def write() -> dict[str, Any]:
            events = self._read_unlocked()
            payload = {
                "schema_version": LEDGER_SCHEMA_VERSION,
                "seq": len(events) + 1,
                "event_id": uuid.uuid4().hex,
                "event": resolved_type,
                "time": datetime.now().astimezone().isoformat(timespec="microseconds"),
                **data,
            }
            parent = os.path.dirname(self.path)
            if parent:
                os.makedirs(parent, exist_ok=True)
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n"
            with open(self.path, "a", encoding="utf-8", newline="") as handle:
                handle.write(line)
                handle.flush()
                os.fsync(handle.fileno())
            return payload

        try:
            return run_with_interprocess_lock(self.lock_path, write)
        except Exception as exc:
            raise AgentStepLedgerError(f"agent step checkpoint failed: {type(exc).__name__}: {exc}") from exc

    def read(self) -> list[dict[str, Any]]:
        try:
            return run_with_interprocess_lock(self.lock_path, self._read_unlocked)
        except Exception as exc:
            raise AgentStepLedgerError(f"agent step ledger read failed: {type(exc).__name__}: {exc}") from exc

    def unknown_tool_outcomes(self) -> list[UnknownToolOutcome]:
        starts: dict[str, dict[str, Any]] = {}
        finished: set[str] = set()
        for event in self.read():
            event_type = str(event.get("event") or "")
            call_id = str(event.get("call_id") or "").strip()
            if not call_id:
                continue
            if event_type == "tool_call_started":
                starts[call_id] = event
            elif event_type in {"tool_call_finished", "tool_outcome_unknown_resolved"}:
                finished.add(call_id)
        output: list[UnknownToolOutcome] = []
        for call_id, event in starts.items():
            if call_id in finished:
                continue
            arguments = event.get("arguments")
            output.append(
                UnknownToolOutcome(
                    call_id=call_id,
                    tool_name=str(event.get("tool") or "tool").strip() or "tool",
                    arguments=dict(arguments) if isinstance(arguments, dict) else {},
                    step_id=str(event.get("step_id") or "").strip(),
                )
            )
        return output

    def latest_compaction_checkpoint(self) -> dict[str, Any] | None:
        for event in reversed(self.read()):
            if str(event.get("event") or "") == "session_context_compacted":
                return event
        return None

    def latest_open_step_id(self) -> str:
        open_steps: dict[str, bool] = {}
        for event in self.read():
            step_id = str(event.get("step_id") or "")
            if not step_id:
                continue
            if event.get("event") == "provider_request_started":
                open_steps[step_id] = True
            elif event.get("event") == "step_closed":
                open_steps.pop(step_id, None)
        return next(reversed(open_steps), "") if open_steps else ""

    def recovered_unknown_call_ids(self) -> set[str]:
        return {
            str(event.get("call_id") or "")
            for event in self.read()
            if event.get("event") == "tool_outcome_recovered" and str(event.get("call_id") or "")
        }

    def _read_unlocked(self) -> list[dict[str, Any]]:
        if not os.path.isfile(self.path):
            return []
        events: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, start=1):
                text = line.strip()
                if not text:
                    continue
                try:
                    payload = json.loads(text)
                except json.JSONDecodeError as exc:
                    raise AgentStepLedgerError(
                        f"invalid agent step ledger JSON at line {line_number}: {exc}"
                    ) from exc
                if not isinstance(payload, dict):
                    raise AgentStepLedgerError(
                        f"agent step ledger line {line_number} must be an object"
                    )
                events.append(payload)
        return events


class AgentStepLedgerMixin:
    def _agent_step_ledger_enabled(self) -> bool:
        value = getattr(self, "config", {}).get("agentStepLedgerEnabled", False)
        if not isinstance(value, bool):
            raise ValueError("provider.agentStepLedgerEnabled must be a boolean")
        return value

    def _agent_step_ledger(self) -> AgentStepLedger | None:
        if not self._agent_step_ledger_enabled():
            return None
        path = self._agent_step_ledger_path()
        existing = getattr(self, "_agentpark_step_ledger", None)
        if isinstance(existing, AgentStepLedger) and existing.path == path:
            return existing
        ledger = AgentStepLedger(path)
        self._agentpark_step_ledger = ledger
        return ledger

    def _agent_step_ledger_path(self) -> str:
        from src.providers.agent_runtime_context import get_agent_runtime_context

        runtime_context = get_agent_runtime_context(self)
        root = str(runtime_context.node_directory or "").strip()
        if not root:
            memory = getattr(self, "memory", None)
            memory_path = str(getattr(memory, "current_memory_path", "") or "").strip()
            root = os.path.dirname(os.path.abspath(memory_path)) if memory_path else ""
        if not root:
            raise AgentStepLedgerError("agent step ledger requires a node directory or memory path")
        return os.path.join(root, LEDGER_FILENAME)

    def _checkpoint_provider_request(self, *, request_api: str, request_summary: object = None) -> str:
        ledger = self._agent_step_ledger()
        if ledger is None:
            callback = getattr(self, "_session_context_compaction_provider_request_checkpointed", None)
            if callable(callback):
                callback()
            return ""
        step_id = str(getattr(self, "_agentpark_current_step_id", "") or "")
        if step_id:
            self._close_current_agent_step(reason="next_provider_request")
        else:
            interrupted_step_id = ledger.latest_open_step_id()
            if interrupted_step_id:
                ledger.append("step_closed", step_id=interrupted_step_id, reason="process_recovered")
        step_id = uuid.uuid4().hex
        self._agentpark_current_step_id = step_id
        request_id = uuid.uuid4().hex
        self._agentpark_current_request_id = request_id
        summary = request_summary if isinstance(request_summary, dict) else {}
        ledger.append(
            "provider_request_started",
            step_id=step_id,
            request_id=request_id,
            provider=str(getattr(self, "provider_name", "") or ""),
            model=str(getattr(self, "config", {}).get("model") or ""),
            request_api=str(request_api or "").strip(),
            request_index=summary.get("request_index"),
        )
        callback = getattr(self, "_session_context_compaction_provider_request_checkpointed", None)
        if callable(callback):
            callback()
        return step_id

    def _record_provider_response(self, result: object) -> None:
        ledger = self._agent_step_ledger()
        step_id = str(getattr(self, "_agentpark_current_step_id", "") or "")
        if ledger is None or not step_id:
            return
        request_id = str(getattr(self, "_agentpark_current_request_id", "") or "")
        response_id = str(result.get("id") or "") if isinstance(result, dict) else ""
        ledger.append(
            "provider_response_received",
            step_id=step_id,
            request_id=request_id,
            response_id=response_id,
        )

    def _record_provider_failure(self, error: BaseException, *, terminal: bool = True) -> None:
        ledger = self._agent_step_ledger()
        step_id = str(getattr(self, "_agentpark_current_step_id", "") or "")
        if ledger is None or not step_id:
            return
        request_id = str(getattr(self, "_agentpark_current_request_id", "") or "")
        ledger.append(
            "provider_request_failed",
            step_id=step_id,
            request_id=request_id,
            error=f"{type(error).__name__}: {error}",
        )
        if terminal:
            self._close_current_agent_step(reason="provider_failure")

    def _record_provider_retry_scheduled(
        self,
        *,
        stage: str,
        attempt: int,
        max_retries: int,
        error: object,
    ) -> None:
        ledger = self._agent_step_ledger()
        step_id = str(getattr(self, "_agentpark_current_step_id", "") or "")
        if ledger is None or not step_id:
            return
        ledger.append(
            "provider_retry_scheduled",
            step_id=step_id,
            request_id=str(getattr(self, "_agentpark_current_request_id", "") or ""),
            stage=str(stage or "provider_retry"),
            attempt=int(attempt),
            max_retries=int(max_retries),
            error=str(error or ""),
        )

    def _record_provider_retry_started(self, *, stage: str, attempt: int) -> None:
        ledger = self._agent_step_ledger()
        step_id = str(getattr(self, "_agentpark_current_step_id", "") or "")
        if ledger is None or not step_id:
            return
        ledger.append(
            "provider_retry_started",
            step_id=step_id,
            request_id=str(getattr(self, "_agentpark_current_request_id", "") or ""),
            stage=str(stage or "provider_retry"),
            attempt=int(attempt),
        )

    def _close_current_agent_step(self, *, reason: str) -> None:
        ledger = self._agent_step_ledger()
        step_id = str(getattr(self, "_agentpark_current_step_id", "") or "")
        if ledger is None or not step_id:
            return
        ledger.append("step_closed", step_id=step_id, reason=str(reason or "completed"))
        self._agentpark_current_step_id = ""
        self._agentpark_current_request_id = ""

    def _record_tool_call_started(self, call: object) -> None:
        ledger = self._agent_step_ledger()
        if ledger is None:
            return
        arguments = getattr(call, "arguments", None)
        ledger.append(
            "tool_call_started",
            step_id=str(getattr(self, "_agentpark_current_step_id", "") or ""),
            call_id=str(getattr(call, "call_id", "") or ""),
            tool=str(getattr(call, "name", "") or "tool"),
            arguments=dict(arguments) if isinstance(arguments, dict) else {},
        )

    def _record_tool_call_finished(self, call: object, *, status: str, error: object = "") -> None:
        ledger = self._agent_step_ledger()
        if ledger is None:
            return
        ledger.append(
            "tool_call_finished",
            step_id=str(getattr(self, "_agentpark_current_step_id", "") or ""),
            call_id=str(getattr(call, "call_id", "") or ""),
            tool=str(getattr(call, "name", "") or "tool"),
            status=str(status or "completed"),
            error=str(error or ""),
        )

    def _inject_unknown_tool_outcomes(self) -> list[dict[str, Any]]:
        if bool(getattr(self, "_agentpark_unknown_tool_outcomes_injected", False)):
            return []
        ledger = self._agent_step_ledger()
        if ledger is None:
            return []
        outcomes = ledger.unknown_tool_outcomes()
        self._agentpark_unknown_tool_outcomes_injected = True
        if not outcomes:
            return []
        payloads = [item.to_payload() for item in outcomes]
        recovered_call_ids = ledger.recovered_unknown_call_ids()
        for outcome, payload in zip(outcomes, payloads):
            if outcome.call_id in recovered_call_ids:
                continue
            ledger.append(
                "tool_outcome_recovered",
                step_id=outcome.step_id,
                call_id=outcome.call_id,
                tool=outcome.tool_name,
                synthetic_result=payload,
            )
        calls = [
            {
                "id": outcome.call_id,
                "type": "function",
                "function": {
                    "name": outcome.tool_name,
                    "arguments": json.dumps(outcome.arguments, ensure_ascii=False, separators=(",", ":")),
                },
            }
            for outcome in outcomes
        ]
        recovery_messages = [{"role": "assistant", "content": None, "tool_calls": calls}]
        recovery_messages.extend(
            {
                "role": "tool",
                "content": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                "name": outcome.tool_name,
                "tool_call_id": outcome.call_id,
            }
            for outcome, payload in zip(outcomes, payloads)
        )
        insert_at = max(
            (
                index
                for index, message in enumerate(self.messages)
                if isinstance(message, dict) and str(message.get("role") or "").lower() == "user"
            ),
            default=len(self.messages),
        )
        self.messages[insert_at:insert_at] = recovery_messages
        return payloads


__all__ = [
    "AgentStepLedger",
    "AgentStepLedgerError",
    "AgentStepLedgerMixin",
    "LEDGER_FILENAME",
    "TOOL_OUTCOME_UNKNOWN",
    "UnknownToolOutcome",
]
