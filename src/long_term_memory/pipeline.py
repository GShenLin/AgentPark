from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

from src.file_transaction import atomic_write_text
from .contracts import Consolidation, Extraction, MemoryModel, digest, encode
from .jobs import LeaseLost, PipelineLease
from .privacy import redact
from .prompts import instructions
from .settings import MemorySettings
from .sources import load_sources
from .store import MemoryStore
from .artifacts import prune_generations


class MemoryPipeline:
    def __init__(self, store: MemoryStore, model: MemoryModel, settings: MemorySettings):
        self.store, self.model, self.settings = store, model, settings

    def run(self, *, active_trace: str = "", now: float | None = None) -> dict:
        now = time.time() if now is None else now
        if not self.settings.enabled:
            return {"status": "disabled"}
        lease = PipelineLease(self.store, self.settings.lease_seconds)
        if not lease.claim():
            return {"status": "busy_or_backoff"}
        report = {"extracted": 0, "no_output": 0, "failed": 0, "published": False}
        with self.store.connect() as db:
            run_id = db.execute("INSERT INTO runs(started_at,status) VALUES(?,'running')", (now,)).lastrowid
        try:
            self.store.sync(load_sources(self.store.node_dir))
            self._extract(lease, report, now, active_trace)
            self._consolidate(lease, report, now)
            report["status"] = "partial_failure" if report["failed"] else "succeeded"
            lease.finish()
        except Exception as exc:
            report.update(status="failed", error=redact(f"{type(exc).__name__}: {exc}"))
            lease.finish(error=report["error"], retry_seconds=0 if isinstance(exc, LeaseLost) else self.settings.retry_seconds)
            raise
        finally:
            with self.store.connect() as db:
                db.execute("UPDATE runs SET finished_at=?,status=?,details=? WHERE id=?",
                           (time.time(), report.get("status", "failed"), encode(report), run_id))
        return report

    def _extract(self, lease: PipelineLease, report: dict, now: float, active_trace: str):
        cfg = self.settings
        with self.store.connect() as db:
            candidates = [dict(r) for r in db.execute("""SELECT * FROM sources WHERE complete=1
                AND status IN ('pending','failed') AND retry_at<=? AND updated_at<=? AND updated_at>=?
                AND trace_id<>? ORDER BY updated_at DESC,id LIMIT ?""",
                (now, now - cfg.min_idle_seconds, now - cfg.max_age_days * 86400, active_trace, cfg.max_extractions))]
        for row in candidates:
            try:
                payload = {"source_id": row["id"], "trace_id": row["trace_id"], "records": json.loads(row["payload"])}
                if len(encode(payload).encode("utf-8")) > cfg.input_bytes:
                    raise ValueError("source exceeds memory extraction input budget; increase input_bytes explicitly")
                output = Extraction.parse(self.model.complete("extract", instructions("extract"), payload))
                with self.store.connect() as db:
                    lease.check(db)
                    db.execute("""UPDATE sources SET status=?,summary=?,slug=?,error='',attempts=attempts+1
                        WHERE id=? AND fingerprint=?""", ("succeeded" if output.rollout_summary else "no_output",
                        redact(output.rollout_summary), redact(output.rollout_slug), row["id"], row["fingerprint"]))
                report["extracted" if output.rollout_summary else "no_output"] += 1
            except LeaseLost:
                raise
            except Exception as exc:
                with self.store.connect() as db:
                    lease.check(db)
                    db.execute("""UPDATE sources SET status='failed',attempts=attempts+1,error=?,retry_at=?
                        WHERE id=? AND fingerprint=?""", (redact(f"{type(exc).__name__}: {exc}"),
                        now + cfg.retry_seconds, row["id"], row["fingerprint"]))
                report["failed"] += 1

    def _consolidate(self, lease: PipelineLease, report: dict, now: float):
        cfg = self.settings
        revision = self.store.state()["revision"]
        selected = self.store.selected(limit=cfg.max_selected, cutoff=now - cfg.max_unused_days * 86400,
                                       byte_budget=cfg.consolidation_bytes // 2)
        notes = self.store.notes()
        manifest = {"sources": {r["id"]: r["fingerprint"] for r in selected}, "notes": notes}
        old = self.store.publication()
        if old and old["manifest"] == manifest:
            return
        previous = old["manifest"]["sources"] if old else {}
        current = manifest["sources"]
        payload = {"sources": selected, "user_edits": notes, "previous_summary": old["summary"] if old else "",
                   "added": sorted(set(current) - set(previous)), "deleted": sorted(set(previous) - set(current)),
                   "changed": sorted(k for k in set(current) & set(previous) if current[k] != previous[k])}
        if len(encode(payload).encode("utf-8")) > cfg.consolidation_bytes:
            raise ValueError("consolidation input exceeds configured budget")
        if not selected and not notes:
            output = Consolidation("v1\n\n## User Profile\n\n## User preferences\n\n## General Tips\n\n## What's in Memory", ())
        else:
            output = Consolidation.parse(self.model.complete("consolidate", instructions("consolidate"), payload), set(current))
        # Recheck the source files after slow inference, not just the old DB snapshot.
        self.store.sync(load_sources(self.store.node_dir))
        generation = digest(manifest) + "-" + uuid.uuid4().hex
        folder = self.store.root / "generations" / generation
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            lease.check(db)
            if db.execute("SELECT revision FROM owner").fetchone()[0] != revision:
                raise LeaseLost("source history changed during consolidation; publication rejected")
            folder.mkdir(parents=True)
            for row in selected:
                atomic_write_text(str(folder / (row["id"] + ".md")), row["summary"])
            atomic_write_text(str(folder / "memory_summary.md"), redact(output.memory_summary))
            atomic_write_text(str(folder / "manifest.json"), encode(manifest))
            db.execute("UPDATE owner SET publication=?", (generation,))
        with self.store.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            prune_generations(self.store.root, db.execute("SELECT publication FROM owner").fetchone()[0])
        report["published"] = True
