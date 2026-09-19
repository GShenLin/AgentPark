"""Reproducible local scale probe; synthetic vectors, no external model calls.

python -m scripts.benchmark_knowledge --documents 300000 --vectors 10000 --files 10000
All artifacts live in a new temporary directory and are removed on exit.
"""
import argparse
import json
from pathlib import Path
import tempfile
import threading
import time
import tracemalloc

from src.knowledge.database import Database
from src.knowledge.scanner import begin_scan, scan
from src.knowledge.vectors import VectorIndex


def measure(documents: int, vector_count: int, files: int):
    result = {"documents": documents, "vectors": vector_count, "filesystem_files": files,
              "note": "Synthetic metadata/vectors; not an end-to-end PDF or embedding-provider throughput claim."}
    with tempfile.TemporaryDirectory(prefix="agentpark-knowledge-benchmark-") as directory:
        root = Path(directory)
        store = Database(root / "catalog")
        store.initialize()
        tracemalloc.start()
        started = time.perf_counter()
        for start in range(0, documents, 1000):
            with store.connect() as db:
                db.executemany("INSERT INTO documents(path,size,mtime_ns,seen,state) VALUES(?,100,1,1,'ready')",
                               ((f"notes/{index:08}.md",) for index in range(start, min(start + 1000, documents))))
        result["catalog_insert_seconds"] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        status = store.status()
        result["status_seconds"] = round(time.perf_counter() - started, 4)
        assert status["documents"]["ready"] == documents
        started = time.perf_counter()
        page = store.documents(after=max(0, documents - 100), limit=50)
        result["late_page_seconds"] = round(time.perf_counter() - started, 4)
        assert len(page["items"]) == min(50, documents)
        result["catalog_python_peak_mb"] = round(tracemalloc.get_traced_memory()[1] / 1048576, 2)
        tracemalloc.stop()
        folder = root / "notes"
        folder.mkdir()
        for index in range(files):
            (folder / f"{index:07}.md").write_text("synthetic note", encoding="utf-8")
        scan_store = Database(root / "scanner")
        scan_store.initialize()
        begin_scan(scan_store)
        tracemalloc.start()
        started = time.perf_counter()
        scan(scan_store, folder, threading.Event())
        result["folder_scan_seconds"] = round(time.perf_counter() - started, 3)
        result["scan_python_peak_mb"] = round(tracemalloc.get_traced_memory()[1] / 1048576, 2)
        tracemalloc.stop()
        assert scan_store.status()["discovered"] == files
        import numpy as np
        rng = np.random.default_rng(42)
        vector_index = VectorIndex(root / "ann", 128)
        started = time.perf_counter()
        for start in range(0, vector_count, 512):
            ids = list(range(start, min(start + 512, vector_count)))
            values = rng.normal(size=(len(ids), 128)).astype('float32')
            vector_index.put(ids, values.tolist())
            vector_index.publish(ids)
        result["vector_insert_seconds"] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        vector_index.maintain()
        result["ann_build_seconds"] = round(time.perf_counter() - started, 3)
        started = time.perf_counter()
        hits = vector_index.search(rng.normal(size=128).tolist(), limit=100)
        result["ann_search_seconds"] = round(time.perf_counter() - started, 4)
        result["ann_results"] = len(hits)
        result["total_disk_mb"] = round(sum(p.stat().st_size for p in root.rglob('*') if p.is_file()) / 1048576, 2)
        del vector_index
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--documents", type=int, default=300000)
    parser.add_argument("--vectors", type=int, default=10000)
    parser.add_argument("--files", type=int, default=10000)
    args = parser.parse_args()
    print(json.dumps(measure(args.documents, args.vectors, args.files), indent=2))
