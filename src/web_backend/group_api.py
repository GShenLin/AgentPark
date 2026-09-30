"""HTTP boundary for graph-local collaboration. Agent tools use the domain directly."""
from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request

from src.agent_groups.contracts import (
    CreateGroup, CreateTask, GroupConflict, GroupError, GroupNotFound,
    GroupPermissionError, MoveMember, PublishMessage, UpdateGroup, UpdateTask, UpdateMemberRole, UpdatePlan,
)
from src.agent_groups.membership import GroupMembership
from src.agent_groups.messages import GroupMessages
from src.agent_groups.repository import GroupRepository
from src.agent_groups.tasks import GroupTasks
from src.agent_groups.delivery import GroupDelivery
from .request_access import has_owner_access
from .graph_grid_layout import graph_layout_lock
from .group_spatial_layout import read_group_layout
from src.agent_groups.spatial_membership import covered


@contextmanager
def group_errors():
    try:
        yield
    except GroupNotFound as exc:
        raise HTTPException(404, str(exc)) from exc
    except GroupPermissionError as exc:
        raise HTTPException(403, str(exc)) from exc
    except GroupConflict as exc:
        raise HTTPException(409, str(exc)) from exc
    except GroupError as exc:
        raise HTTPException(400, str(exc)) from exc


class GroupApi:
    def __init__(self, core):
        self.core = core

    def repository(self, graph_id: str, request: Request, *, write: bool = False) -> GroupRepository:
        safe = self.core.graph_runtime._sanitize_graph_id(graph_id)
        if safe != graph_id:
            raise HTTPException(400, "invalid graph id")
        self.core.graph_api.require_graph_visible(graph_id, request)
        role = self.core.access_api.message_access_metadata(request)["_access_role"] if write else "developer"
        with group_errors():
            return GroupRepository(Path(self.core.graph_runtime._graph_dir(graph_id)), access_role=role)

    def visible(self, graph_id: str, group, request: Request) -> bool:
        if has_owner_access(request):
            return True
        if group.private:
            return False
        return not any(self.core.node_ops._node_is_private(graph_id, member.node_id)
                       for member in group.members)

    def require_group(self, repo, graph_id: str, group_id: str, request: Request):
        with group_errors():
            group = repo.get(group_id)
        if not self.visible(graph_id, group, request):
            raise HTTPException(404, "group not found")
        return group

    def list_groups(self, graph_id: str, request: Request):
        repo = self.repository(graph_id, request)
        return {"groups": [g.model_dump() for g in repo.list() if self.visible(graph_id, g, request)]}

    def get_group(self, graph_id: str, group_id: str, request: Request):
        repo = self.repository(graph_id, request)
        return self.require_group(repo, graph_id, group_id, request)

    def create_group(self, graph_id: str, payload: CreateGroup, request: Request):
        repo = self.repository(graph_id, request, write=True)
        for member in payload.members:
            self.core.node_ops.require_node_visible(member.node_id, graph_id, request)
        private = any(self.core.node_ops._node_is_private(graph_id, m.node_id) for m in payload.members)
        with group_errors():
            return GroupMembership(repo).create(payload, private=private)

    def update_group(self, graph_id: str, group_id: str, payload: UpdateGroup, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            if payload.bounds is not None:
                directory = self.core.graph_runtime._graph_dir(graph_id)
                with graph_layout_lock(directory):
                    layout = read_group_layout(directory, payload.bounds,
                        lambda node: self.core.node_ops._node_is_private(graph_id, node))
                    for node in layout:
                        if covered(payload.bounds, node):
                            self.core.node_ops.require_node_visible(node.node_id, graph_id, request)
                    return GroupMembership(repo).configure(group_id, payload.expected_revision,
                        name=payload.name, objective=payload.objective, bounds=payload.bounds, layout=layout)
            return GroupMembership(repo).configure(group_id, payload.expected_revision,
                name=payload.name, objective=payload.objective, bounds=payload.bounds)

    def update_plan(self, graph_id: str, group_id: str, payload: UpdatePlan, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            return GroupMembership(repo).update_plan(group_id, payload)

    def dissolve_group(self, graph_id: str, group_id: str, request: Request,
                       expected_revision: int = Query(ge=1)):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            GroupMembership(repo).dissolve(group_id, expected_revision)
        return {"ok": True}

    def move_member(self, graph_id: str, node_id: str, payload: MoveMember, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        for group_id in (payload.expected_source, payload.target_group_id):
            if group_id:
                self.require_group(repo, graph_id, group_id, request)
        private = self.core.node_ops._node_is_private(graph_id, node_id)
        with group_errors():
            group = GroupMembership(repo).move(node_id, payload.target_group_id,
                expected_source=payload.expected_source, role=payload.role, private=private)
        return {"group": group}

    def update_member_role(self, graph_id: str, group_id: str, node_id: str,
                           payload: UpdateMemberRole, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        self.core.node_ops.require_node_visible(node_id, graph_id, request)
        with group_errors():
            return GroupMembership(repo).update_role(group_id, node_id, **payload.model_dump())

    def list_events(self, graph_id: str, group_id: str, request: Request,
                    after: int = Query(default=0, ge=0), limit: int = Query(default=100, ge=1, le=500),
                    latest: bool = False, before: int = Query(default=0, ge=0)):
        repo = self.repository(graph_id, request)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            return repo.events(group_id, after=after, limit=limit, latest=latest, before=before)

    def send_message(self, graph_id: str, group_id: str, payload: PublishMessage, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            return GroupMessages(repo).publish(group_id, payload, None)

    def delivery_status(self, graph_id: str, group_id: str, request: Request):
        repo = self.repository(graph_id, request)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            return {"deliveries": GroupDelivery(repo).status(group_id)}

    def create_task(self, graph_id: str, group_id: str, payload: CreateTask, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            return GroupTasks(repo).create(group_id, payload, None)

    def update_task(self, graph_id: str, group_id: str, task_id: str, payload: UpdateTask, request: Request):
        repo = self.repository(graph_id, request, write=True)
        self.require_group(repo, graph_id, group_id, request)
        with group_errors():
            return GroupTasks(repo).update(group_id, task_id, payload, None)


def register_group_routes(app, core):
    api = GroupApi(core)
    router = APIRouter(prefix="/api/graphs/{graph_id}", tags=["groups"])
    router.add_api_route("/groups", api.list_groups, methods=["GET"])
    router.add_api_route("/groups", api.create_group, methods=["POST"])
    router.add_api_route("/groups/{group_id}", api.get_group, methods=["GET"])
    router.add_api_route("/groups/{group_id}", api.update_group, methods=["PATCH"])
    router.add_api_route("/groups/{group_id}/plan", api.update_plan, methods=["PATCH"])
    router.add_api_route("/groups/{group_id}", api.dissolve_group, methods=["DELETE"])
    router.add_api_route("/group-members/{node_id}", api.move_member, methods=["PUT"])
    router.add_api_route("/groups/{group_id}/members/{node_id}", api.update_member_role, methods=["PATCH"])
    router.add_api_route("/groups/{group_id}/events", api.list_events, methods=["GET"])
    router.add_api_route("/groups/{group_id}/messages", api.send_message, methods=["POST"])
    router.add_api_route("/groups/{group_id}/deliveries", api.delivery_status, methods=["GET"])
    router.add_api_route("/groups/{group_id}/tasks", api.create_task, methods=["POST"])
    router.add_api_route("/groups/{group_id}/tasks/{task_id}", api.update_task, methods=["PATCH"])
    app.include_router(router)
