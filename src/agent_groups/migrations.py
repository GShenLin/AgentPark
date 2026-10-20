"""One-time conversions of durable notifications, not runtime legacy routing."""
import json

from .contracts import AgentGroup
from .task_notifications import ready


def upgrade_group_leaders(db):
    """Version 5: persist the first member as leader for existing groups.

    Previously submitted messages keep their original recipients and audit trail.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        if db.execute('PRAGMA user_version').fetchone()[0] < 5:
            for row in db.execute('SELECT id,document FROM groups').fetchall():
                document = json.loads(row['document'])
                if 'leader_id' not in document:
                    document['leader_id'] = document['members'][0]['node_id'] if document['members'] else None
                    db.execute('UPDATE groups SET document=? WHERE id=?',
                               (json.dumps(document, ensure_ascii=False), row['id']))
            db.execute('PRAGMA user_version=5')
        db.commit()
    except BaseException:
        db.rollback()
        raise


def upgrade_task_notifications(db):
    """Version 4: restrict pending old task broadcasts to still-relevant owners.

    Old records did not identify the task that each recipient should act on.
    Materialize that identity once from the persisted task and dependency graph;
    obsolete informational recipients are cancelled. User/peer messages are untouched.
    """
    db.execute('BEGIN IMMEDIATE')
    try:
        rows = db.execute("""SELECT DISTINCT e.seq,e.group_id,e.payload FROM events e
            JOIN deliveries d ON d.event_seq=e.seq WHERE d.state='pending'
            AND e.kind IN ('task_created','task_updated')""").fetchall()
        for row in rows:
            payload = json.loads(row['payload'])
            if 'action_tasks' in payload:
                continue
            document = db.execute('SELECT document FROM groups WHERE id=?', (row['group_id'],)).fetchone()[0]
            group = AgentGroup.model_validate_json(document)
            source = payload['task']
            members = {m.node_id for m in group.members}
            actions = {}
            for task in group.tasks:
                related = (source['id'] in task.dependencies if source['status'] == 'done'
                           else source['id'] == task.id)
                if not group.dissolved and related and task.owner_id in members and ready(group, task):
                    actions.setdefault(task.owner_id, []).append(task.id)
            payload['action_tasks'] = actions
            db.execute('UPDATE events SET payload=? WHERE seq=?',
                       (json.dumps(payload, ensure_ascii=False), row['seq']))
            recipients = db.execute("SELECT node_id FROM deliveries WHERE event_seq=? AND state='pending'",
                                    (row['seq'],)).fetchall()
            for recipient in recipients:
                if recipient['node_id'] not in actions:
                    db.execute("UPDATE deliveries SET state='cancelled' WHERE event_seq=? AND node_id=?",
                               (row['seq'], recipient['node_id']))
        db.execute('PRAGMA user_version=4')
        db.commit()
    except BaseException:
        db.rollback()
        raise
