from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

from src.public_gateway.usage_stats import PublicGatewayUsageStore


_LOGGER = logging.getLogger(__name__)


def build_agent_gateway_usage_recorder(
    *,
    workspace_root: str,
    client_ip: str,
    task_id: str,
    model_id: str,
) -> Callable[[dict[str, Any]], None] | None:
    safe_ip = str(client_ip or "").strip()
    safe_model = str(model_id or "").strip()
    safe_task = str(task_id or "").strip()
    if not safe_ip or not safe_model or not safe_task:
        return None
    store = PublicGatewayUsageStore(workspace_root)

    def record(completion: dict[str, Any]) -> None:
        request_index = completion.get("request_index")
        try:
            store.record_completed(
                request_id=f"agent:{safe_task}:{request_index}",
                client_ip=safe_ip,
                model_id=safe_model,
                protocol=str(completion.get("request_api") or "provider"),
                usage=completion.get("usage"),
                source="agent_node",
            )
        except Exception:
            _LOGGER.exception(
                "Failed to record Agent node Gateway usage for task=%s request=%s",
                safe_task,
                request_index,
            )

    return record


__all__ = ["build_agent_gateway_usage_recorder"]
