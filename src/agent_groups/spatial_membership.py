"""Atomic frame membership reconciliation, independent of canvas/file storage."""
from dataclasses import dataclass

from .contracts import AgentGroup, GroupBounds, GroupConflict, GroupMember
from .node_lifecycle import detach_member


@dataclass(frozen=True)
class SpatialMember:
    node_id: str
    x: float
    y: float
    private: bool = False


def covered(bounds: GroupBounds, node: SpatialMember) -> bool:
    return (bounds.x <= node.x < bounds.x + bounds.width
            and bounds.y <= node.y < bounds.y + bounds.height)


def reconcile(repo, db, group: AgentGroup, bounds: GroupBounds, nodes: list[SpatialMember]):
    for row in db.execute("SELECT document FROM groups"):
        other = AgentGroup.model_validate_json(row[0])
        b = other.bounds
        if not other.dissolved and other.id != group.id and (
            bounds.x < b.x + b.width and bounds.x + bounds.width > b.x
            and bounds.y < b.y + b.height and bounds.y + bounds.height > b.y
        ):
            raise GroupConflict("组范围不能与其他组重叠；请调整边框后重试。")
    members = {node.node_id: node for node in nodes if covered(bounds, node)}
    for node_id in members:
        row = db.execute("SELECT group_id FROM members WHERE node_id=?", (node_id,)).fetchone()
        if row and row[0] != group.id:
            raise GroupConflict("范围内的 Agent 已属于其他组，请先调整其成员关系。")
    for member in list(group.members):
        if member.node_id not in members:
            detach_member(repo, db, group, member.node_id, reason="frame_resized")
    existing = {member.node_id for member in group.members}
    for node_id, node in members.items():
        if node_id not in existing:
            member = GroupMember(node_id=node_id)
            group.members.append(member)
            group.private = group.private or node.private
            db.execute("INSERT INTO members VALUES(?,?)", (node_id, group.id))
            repo.save(db, group)
            repo.event(db, group, "member_joined", None, {"member": member.model_dump()}, recipients=[])
