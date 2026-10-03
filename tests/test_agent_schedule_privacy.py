from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.web_backend.memory_static_files import VisibilityAwareMemoriesStaticFiles


@pytest.mark.parametrize("suffix", ["", "-wal", "-shm", "-journal"])
@pytest.mark.parametrize("prefix", ["", "public/"])
def test_schedule_database_is_never_publicly_downloadable(tmp_path, suffix, prefix):
    filename = prefix + "agent-schedules.sqlite3" + suffix
    path = tmp_path / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"private task and access metadata")
    app = FastAPI()
    # No visibility calls should be needed: even public graphs must not expose DBs.
    app.mount("/memories", VisibilityAwareMemoriesStaticFiles(directory=str(tmp_path), core=SimpleNamespace()))
    response = TestClient(app).get("/memories/" + filename)
    assert response.status_code == 404
    assert b"private task" not in response.content
