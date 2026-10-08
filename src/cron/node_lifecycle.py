"""Keep schedule ownership aligned with explicit node lifecycle operations."""
from contextlib import contextmanager
from pathlib import Path
import time

from .repository import CronRepository


@contextmanager
def cron_node_departure(graph_directory: str, node_id: str):
    directory = Path(graph_directory)
    if not (directory / "cron.sqlite3").is_file():
        yield
        return
    with CronRepository(directory).transaction() as db:
        db.execute("DELETE FROM jobs WHERE node_id=?", (node_id,))
        db.execute("UPDATE runs SET status='cancelled',finished_at=?,error='Owning node left the graph' "
                   "WHERE node_id=? AND status IN ('pending','running')", (time.time(), node_id))
        yield


@contextmanager
def cron_node_rename(graph_directory: str, old: str, new: str):
    directory = Path(graph_directory)
    if old == new or not (directory / "cron.sqlite3").is_file():
        yield
        return
    with CronRepository(directory).transaction() as db:
        if db.execute("SELECT 1 FROM jobs WHERE node_id=?", (new,)).fetchone():
            raise ValueError("target node identity already owns cron schedules")
        db.execute("UPDATE jobs SET node_id=? WHERE node_id=?", (new, old))
        db.execute("UPDATE runs SET node_id=? WHERE node_id=?", (new, old))
        yield
