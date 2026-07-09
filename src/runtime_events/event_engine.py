from __future__ import annotations

import json
import os
import threading
import time
import uuid
from datetime import datetime
from typing import Any

from src.operational_memory import record_operational_memory_entry
from src.web_backend.state_store import _preview_text

from .action_results import context_fragment, notice, truncate_text
from .companion_startup_recovery import CompanionStartupRecovery
from .context_store import RuntimeEventContextStore
from .event_models import CompiledRule, RuntimeEventEnvelope
from .event_registry import EventConfigError, RuntimeEventRegistryManager
from .metrics import RuntimeEventMetrics
from .node_dispatch import RuntimeEventNodeDispatch
from .temporary_receiver_cleanup import TemporaryReceiverCleanup


class RuntimeEventDomain:
    def __init__(self, core: object) -> None:
        self.core = core
        self.metrics = RuntimeEventMetrics()
        self.registry = RuntimeEventRegistryManager(core)
        self.context_store = RuntimeEventContextStore(core, self.metrics)
        self.dispatch = RuntimeEventNodeDispatch(core, self.metrics)
        self.cleanup = TemporaryReceiverCleanup(core, self.metrics)
        self.startup_recovery = CompanionStartupRecovery(core, self.cleanup, self.metrics)
        self._dedupe: dict[str, float] = {}
        self._dedupe_lock = threading.Lock()

    def startup(self) -> dict[str, Any]:
        canonical_result = self.startup_recovery.ensure_canonical_companion()
        config_result = self.registry.load_startup()
        recovery_result = self.startup_recovery.run()
        recovery_result["canonical"] = canonical_result
        return {"config": config_result, "companion_recovery": recovery_result}

    def apply_events_config(self, payload: dict | None = None):
        try:
            config = payload.get("config") if isinstance(payload, dict) and "config" in payload else None
            return self.registry.apply(config if isinstance(config, dict) else None)
        except EventConfigError as exc:
            return {"ok": False, "errors": exc.errors}

    def diagnostics(self):
        active = self.registry.active()
        return {
            "ok": True,
            "enabled": active.enabled,
            "compiled": RuntimeEventRegistryManager._compiled_counts(active),
            "metrics": self.metrics.snapshot(),
            "context_artifacts": self.context_store.snapshot(),
        }

    def emit(
        self,
        *,
        event: str,
        graph_id: str,
        node_id: str,
        node_type_id: str,
        trace_id: str | None = "",
        payload: dict | None = None,
    ) -> dict[str, Any]:
        active = self.registry.active()
        if not active.enabled:
            return {"matched": 0, "executed": 0, "artifacts": 0, "deduped": False, "errors": []}
        event_name = str(event or "").strip()
        key = (str(graph_id or "").strip(), str(node_id or "").strip(), event_name)
        rules = active.rule_index.get(key)
        if not rules:
            self.metrics.inc("event_no_match", event=event_name)
            return {"matched": 0, "executed": 0, "artifacts": 0, "deduped": False, "errors": []}

        envelope = RuntimeEventEnvelope(
            event_id=f"evt_{uuid.uuid4().hex}",
            event=event_name,
            ts=datetime.now().astimezone().isoformat(),
            source_graph_id=key[0],
            source_node_id=key[1],
            source_node_type_id=str(node_type_id or "").strip(),
            trace_id=str(trace_id or "").strip(),
            payload=_bounded_payload(payload or {}),
        )
        self.metrics.inc("event_emitted", event=event_name)
        if self._is_deduped(envelope, active.config):
            self.metrics.inc("event_deduped", event=event_name)
            return {
                "event_id": envelope.event_id,
                "matched": len(rules),
                "executed": 0,
                "artifacts": 0,
                "deduped": True,
                "errors": [],
            }

        errors: list[str] = []
        artifacts = 0
        executed = 0
        for rule in rules:
            try:
                result = self._execute_rule(rule, envelope)
                executed += 1
                if isinstance(result, list):
                    for item in result:
                        artifacts += self._apply_action_result(item, rule, envelope)
                elif isinstance(result, dict):
                    artifacts += self._apply_action_result(result, rule, envelope)
            except Exception as exc:
                errors.append(f"rule[{rule.rule_index}] {type(exc).__name__}: {exc}")
                self.metrics.inc("action_failed", event=event_name, action=rule.action)
        return {
            "event_id": envelope.event_id,
            "matched": len(rules),
            "executed": executed,
            "artifacts": artifacts,
            "deduped": False,
            "errors": errors,
        }

    def consume_context_fragments(self, *, graph_id: str, node_id: str) -> list[str]:
        fragments = self.context_store.consume_for_node(graph_id, node_id)
        if fragments:
            self.metrics.inc("context_injected", count=len(fragments))
        return fragments

    def _execute_rule(self, rule: CompiledRule, envelope: RuntimeEventEnvelope) -> dict[str, Any] | list[dict[str, Any]] | None:
        self.metrics.inc("rule_matched", event=envelope.event, action=rule.action)
        if rule.action == "context.produce":
            return self._produce_context(rule, envelope)
        if rule.action == "notice.write":
            return notice(
                f"Runtime event {envelope.event} matched {envelope.source_graph_id}/{envelope.source_node_id}.",
                level="info",
            )
        if rule.action == "node.dispatch":
            group = self.registry.active().receiver_group_index.get(rule.target)
            if group is None:
                raise ValueError(f"receiver group not found: {rule.target}")
            if bool(envelope.payload.get("suppress_dispatch")):
                return None
            self.dispatch.enqueue(group=group, envelope=envelope)
            return {
                "type": "dispatch_request",
                "receiver_group": group.group_id,
                "event": envelope.event,
                "receiver_graph_id": group.graph_id,
                "profile_id": group.event_profiles.get(envelope.event, ""),
            }
        return None

    def _produce_context(self, rule: CompiledRule, envelope: RuntimeEventEnvelope) -> dict[str, Any] | None:
        policy = self.registry.active().config.get("context_policy")
        policy = policy if isinstance(policy, dict) else {}
        max_chars = int(rule.params.get("max_chars") or policy.get("max_fragment_chars") or 8000)
        ttl = str(rule.params.get("ttl") or policy.get("default_ttl") or "next_turn")
        priority = str(rule.params.get("priority") or self.registry.active().producer_index.get(rule.target, {}).get("priority") or "normal")
        content = ""
        if rule.target == "builtin.environment_context":
            content = self._environment_context(envelope)
        elif rule.target == "builtin.tool_failure_context":
            content = self._tool_failure_context(envelope)
        elif rule.target == "builtin.runtime_notice_context":
            content = self._runtime_notice_context(envelope)
        elif rule.target == "builtin.work_persisted_context":
            content = self._work_context(envelope, failed=False)
        elif rule.target == "builtin.work_failed_context":
            content = self._work_context(envelope, failed=True)
        content = truncate_text(content, max_chars).strip()
        if not content:
            self.metrics.inc("action_no_result", event=envelope.event, action=rule.action, target=rule.target)
            return None
        if ttl == "persistent":
            return {
                "type": "memory_patch",
                "operation": "upsert",
                "target": {
                    "graph_id": envelope.source_graph_id,
                    "node_id": envelope.source_node_id,
                    "memory": "operational_memory",
                },
                "payload": {
                    "kind": "runtime_event_correction",
                    "title": f"{envelope.event} runtime correction",
                    "lesson": content,
                    "evidence": f"runtime event {envelope.event_id}",
                    "reason": f"runtime event {envelope.event}",
                },
            }
        return context_fragment(content, ttl=ttl, priority=priority)

    def _apply_action_result(self, result: dict[str, Any] | None, rule: CompiledRule, envelope: RuntimeEventEnvelope) -> int:
        if not isinstance(result, dict):
            return 0
        result_type = str(result.get("type") or "").strip()
        if result_type == "context_fragment":
            self.context_store.add_fragment(
                graph_id=envelope.source_graph_id,
                node_id=envelope.source_node_id,
                event_id=envelope.event_id,
                ttl=str(result.get("ttl") or "next_turn"),
                priority=str(result.get("priority") or "normal"),
                content=str(result.get("content") or ""),
                audit_payload={"rule_index": rule.rule_index, "event": envelope.event, "target": rule.target},
            )
            self.metrics.inc("context_artifact_produced", event=envelope.event)
            return 1
        if result_type == "notice":
            self.core.graph_runtime._log_graph_event(
                envelope.source_graph_id,
                "runtime_event_notice",
                trace_id=envelope.trace_id,
                node_instance_id=envelope.source_node_id,
                runtime_event=envelope.event,
                message=_preview_text(str(result.get("message") or ""), 1000),
            )
            self.metrics.inc("notice_written", event=envelope.event)
            return 1
        if result_type == "memory_patch":
            self._apply_memory_patch(result, envelope)
            return 1
        if result_type == "dispatch_request":
            self.metrics.inc("dispatch_requested", event=envelope.event)
            return 1
        return 0

    def _apply_memory_patch(self, result: dict[str, Any], envelope: RuntimeEventEnvelope) -> None:
        target = result.get("target") if isinstance(result.get("target"), dict) else {}
        graph_id = str(target.get("graph_id") or envelope.source_graph_id)
        node_id = str(target.get("node_id") or envelope.source_node_id)
        payload = result.get("payload") if isinstance(result.get("payload"), dict) else {}
        operational_path = os.path.join(self.core.graph_runtime._node_dir(graph_id, node_id), "operational_memory.json")
        record_operational_memory_entry(
            path=operational_path,
            action=str(result.get("operation") or "upsert"),
            reason=str(payload.get("reason") or f"runtime event {envelope.event}"),
            kind=str(payload.get("kind") or "runtime_event_correction"),
            title=str(payload.get("title") or f"{envelope.event} correction"),
            lesson=str(payload.get("lesson") or payload.get("evidence") or "See runtime event context."),
            evidence=str(payload.get("evidence") or json.dumps(envelope.to_dict(), ensure_ascii=False)[:1000]),
        )
        self.metrics.inc("memory_patch_applied", event=envelope.event)

    def _is_deduped(self, envelope: RuntimeEventEnvelope, config: dict[str, Any]) -> bool:
        policy = config.get("context_policy") if isinstance(config, dict) else {}
        window_ms = int((policy if isinstance(policy, dict) else {}).get("dedupe_window_ms") or 30000)
        if window_ms <= 0:
            return False
        payload = envelope.payload
        raw = json.dumps(
            {
                "event": envelope.event,
                "graph_id": envelope.source_graph_id,
                "node_id": envelope.source_node_id,
                "tool": payload.get("tool_name"),
                "status": payload.get("status"),
                "error": payload.get("error"),
                "message": payload.get("message"),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        now = time.monotonic()
        with self._dedupe_lock:
            expires_at = self._dedupe.get(raw)
            if expires_at is not None and expires_at > now:
                return True
            self._dedupe[raw] = now + window_ms / 1000
            if len(self._dedupe) > 10000:
                self._dedupe = {key: value for key, value in self._dedupe.items() if value > now}
        return False

    @staticmethod
    def _environment_context(envelope: RuntimeEventEnvelope) -> str:
        return "\n".join(
            [
                "Runtime environment context:",
                f"- Graph/node: {envelope.source_graph_id}/{envelope.source_node_id}",
                f"- Node type: {envelope.source_node_type_id}",
                f"- Current time: {envelope.ts}",
                "- Shell: PowerShell on Windows when running in the default local workspace.",
                "- Prefer commands and paths that match the current operating system.",
            ]
        )

    @staticmethod
    def _tool_failure_context(envelope: RuntimeEventEnvelope) -> str:
        payload = envelope.payload
        tool = str(payload.get("tool_name") or payload.get("name") or "tool").strip()
        status = str(payload.get("status") or "failed").strip()
        error = str(payload.get("error") or payload.get("message") or "").strip()
        if not error and status in {"completed", "success", "ok"}:
            return ""
        return "\n".join(
            [
                "Previous tool call needs correction:",
                f"- Tool: {tool}",
                f"- Status: {status}",
                f"- Error: {error[:2000]}",
                "- Adjust the next action based on this concrete runtime failure.",
            ]
        )

    @staticmethod
    def _runtime_notice_context(envelope: RuntimeEventEnvelope) -> str:
        payload = envelope.payload
        message = str(payload.get("message") or "").strip()
        if not message:
            return ""
        return "\n".join(
            [
                "Runtime notice from the previous run:",
                f"- Source: {payload.get('source') or ''}",
                f"- Stage: {payload.get('stage') or ''}",
                f"- Provider: {payload.get('provider') or ''}",
                f"- Notice: {message[:2000]}",
            ]
        )

    @staticmethod
    def _work_context(envelope: RuntimeEventEnvelope, *, failed: bool) -> str:
        payload = envelope.payload
        if failed:
            return f"Previous work failed: {str(payload.get('error') or payload.get('message') or '')[:2000]}"
        preview = str(payload.get("final_message_preview") or "").strip()
        if not preview:
            return ""
        return f"Previous work was persisted. Final output preview: {preview[:2000]}"


def _bounded_payload(payload: dict[str, Any]) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for key, value in payload.items():
        if isinstance(value, (str, int, float, bool)) or value is None:
            text = value
            if isinstance(value, str):
                text = truncate_text(value, 4000)
            output[str(key)] = text
        elif isinstance(value, dict):
            output[str(key)] = {str(k): truncate_text(v, 1000) for k, v in list(value.items())[:50]}
        elif isinstance(value, list):
            output[str(key)] = [truncate_text(item, 1000) for item in value[:50]]
        else:
            output[str(key)] = truncate_text(value, 1000)
    return output
