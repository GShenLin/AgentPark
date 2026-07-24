from __future__ import annotations

from fastapi import HTTPException, Request

from .domain_base import DomainBase
from src.user_interaction_store import (
    list_interaction_requests,
    read_interaction_request,
    submit_interaction_response,
)


class UserInteractionApiDomain(DomainBase):
    def _require_interaction_visible(self, interaction: dict, request: Request | None) -> None:
        if request is None:
            return
        agent = interaction.get("agent") if isinstance(interaction.get("agent"), dict) else {}
        graph_id = str(agent.get("graph_id") or self.default_graph_id).strip() or self.default_graph_id
        node_id = str(agent.get("node_id") or "").strip()
        if node_id:
            self.core.node_ops.require_node_visible(node_id, graph_id, request)
            return
        self.core.graph_api.require_graph_visible(graph_id, request)

    def list_user_interactions(self, status: str = "pending", request: Request = None):
        try:
            visible_requests = []
            for interaction in list_interaction_requests(status=status):
                try:
                    self._require_interaction_visible(interaction, request)
                except HTTPException as exc:
                    if exc.status_code == 404:
                        continue
                    raise
                visible_requests.append(interaction)
            return {"requests": visible_requests}
        except Exception as exc:
            if isinstance(exc, HTTPException):
                raise
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    def submit_user_interaction(
        self,
        request_id: str,
        payload: dict | None = None,
        request: Request = None,
    ):
        body = payload if isinstance(payload, dict) else {}
        response = body.get("response") if isinstance(body.get("response"), dict) else body
        status = str(body.get("status") or "submitted")
        try:
            self._require_interaction_visible(read_interaction_request(request_id), request)
            completed_request = submit_interaction_response(request_id, response, status=status)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except HTTPException:
            raise
        except Exception as exc:
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        agent = completed_request.get("agent") if isinstance(completed_request.get("agent"), dict) else {}
        graph_id = str(agent.get("graph_id") or self.default_graph_id).strip() or self.default_graph_id
        self.graph_runtime._log_graph_event(
            graph_id,
            f"user_interaction_{str(completed_request.get('status') or 'submitted').strip().lower()}",
            request_id=str(completed_request.get("id") or "").strip(),
            node_instance_id=str(agent.get("node_id") or "").strip() or None,
            node_name=str(agent.get("node_name") or "").strip() or None,
        )
        return {"ok": True, "request": completed_request}
