from datetime import datetime, timezone

from src.message_protocol import build_text_envelope


def run_message(run: dict) -> dict:
    timestamp = datetime.fromtimestamp(run["scheduled_at"], timezone.utc).isoformat()
    return build_text_envelope(
        f"Scheduled task: {run['name']}\nJob ID: {run['job_id']}\nScheduled for: {timestamp}\n\n{run['prompt']}",
        role="user",
    )
