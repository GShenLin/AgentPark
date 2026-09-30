from __future__ import annotations

import uuid

from .contracts import AgentGroup, CreateGroup, GroupBounds, GroupConflict, GroupMember, UpdatePlan
from .repository import GroupRepository, timestamp
from .node_lifecycle import detach_member
from .spatial_membership import SpatialMember, reconcile


class GroupMembership:
    def __init__(self, repository: GroupRepository):
        self.repo = repository

    def create(self, command: CreateGroup, *, private: bool = False) -> AgentGroup:
        now = timestamp()
        group = AgentGroup(id=uuid.uuid4().hex, name=command.name, objective=command.objective,
                           bounds=command.bounds, members=command.members, private=private,
                           created_at=now, updated_at=now)
        with self.repo.transaction() as db:
            for member in group.members:
                if db.execute("SELECT 1 FROM members WHERE node_id=?", (member.node_id,)).fetchone():
                    raise GroupConflict(f"node already belongs to a group: {member.node_id}")
            self.repo.save(db, group, bump=False)
            db.executemany("INSERT INTO members VALUES(?,?)", [(m.node_id, group.id) for m in group.members])
            self.repo.event(db, group, "group_created", None, {"group": group.model_dump()}, recipients=[])
        return group

    def configure(self, group_id: str, expected_revision: int, *, name: str | None = None,
                  objective: str | None = None, bounds: GroupBounds | None = None,
                  layout: list[SpatialMember] | None = None) -> AgentGroup:
        if bounds is not None and layout is None:
            raise GroupConflict("resizing requires an authoritative node layout")
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id)
            if group.revision != expected_revision:
                raise GroupConflict("group changed; refresh before editing")
            if bounds is not None:
                reconcile(self.repo, db, group, bounds, layout)
            changed = {}
            for key, value in (("name", name), ("objective", objective), ("bounds", bounds)):
                if value is not None and getattr(group, key) != value:
                    changed[key] = value.model_dump() if key == "bounds" else value
            if not changed:
                return group
            group = AgentGroup.model_validate({**group.model_dump(), **changed})
            self.repo.save(db, group)
            # Frame changes update UI state, but must not wake agents to discuss geometry.
            self.repo.event(db, group, "group_updated", None, changed,
                            recipients=[])
            return group

    def update_plan(self, group_id: str, command: UpdatePlan) -> AgentGroup:
        """Compare the edited plan, independently of task or membership revisions."""
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id)
            if (group.name, group.objective) != (command.expected_name, command.expected_objective):
                raise GroupConflict("计划已被其他人修改；草稿已保留，请查看最新计划后再编辑。")
            changed = {key: getattr(command, key) for key in ("name", "objective")
                       if getattr(group, key) != getattr(command, key)}
            if changed:
                group = AgentGroup.model_validate({**group.model_dump(), **changed})
                self.repo.save(db, group)
                self.repo.event(db, group, "group_updated", None, changed,
                                recipients=[])
            return group

    def move(self, node_id: str, target_group_id: str | None, *, expected_source: str | None,
             role: str = "", private: bool = False) -> AgentGroup | None:
        member = GroupMember(node_id=node_id, role=role)
        with self.repo.transaction() as db:
            row = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
            source_id = row[0] if row else None
            if source_id != expected_source:
                raise GroupConflict("membership changed; refresh before moving this node")
            target = self.repo.read(db, target_group_id) if target_group_id else None
            if source_id == target_group_id:
                return target
            if source_id:
                source = self.repo.read(db, source_id)
                detach_member(self.repo, db, source, node_id)
            if target:
                # Membership removal must never publish previously private collaboration history.
                target.private = target.private or private
                target.members.append(member)
                db.execute("INSERT INTO members VALUES(?,?)", (node_id, target.id))
                self.repo.save(db, target)
                self.repo.event(db, target, "member_joined", None, {"member": member.model_dump()}, recipients=[])
            return target

    def update_role(self, group_id: str, node_id: str, *, expected_role: str, role: str):
        member = GroupMember(node_id=node_id, role=role)
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id)
            current = next((item for item in group.members if item.node_id == node_id), None)
            if current is None:
                raise GroupConflict("node is no longer a member of this group")
            if current.role != expected_role:
                raise GroupConflict("member role changed; refresh before editing")
            if current.role == member.role:
                return group
            current.role = member.role
            self.repo.save(db, group)
            self.repo.event(db, group, "member_role_updated", None, {"member": member.model_dump()}, recipients=[])
            return group

    def dissolve(self, group_id: str, expected_revision: int):
        with self.repo.transaction() as db:
            group = self.repo.read(db, group_id)
            if group.revision != expected_revision:
                raise GroupConflict("group changed; refresh before dissolving")
            group.dissolved = True
            self.repo.save(db, group)
            db.execute("DELETE FROM members WHERE group_id=?", (group_id,))
            db.execute("""UPDATE deliveries SET state='cancelled' WHERE state='pending'
                AND event_seq IN (SELECT seq FROM events WHERE group_id=?)""", (group_id,))
            self.repo.event(db, group, "group_dissolved", None, {"name": group.name}, recipients=[])
            return group

    def protect_member_history(self, node_id: str):
        """Keep history private when a member becomes private, even after it leaves."""
        with self.repo.transaction() as db:
            row = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
            if row is None:
                return
            group = self.repo.read(db, row[0])
            if not group.private:
                group.private = True
                self.repo.save(db, group)
                self.repo.event(db, group, "group_visibility_changed", None, {"private": True}, recipients=[])
