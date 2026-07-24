import json
import struct
import zlib
from pathlib import Path

from fastapi.testclient import TestClient


def _ansi_field(value: str) -> bytes:
    encoded = value.encode("latin-1")
    assert len(encoded) <= 260
    return struct.pack("<i", 260) + encoded + (b"\0" * (260 - len(encoded)))


def _ue_crash_payload(crash_id: str, files: list[tuple[str, bytes]]) -> bytes:
    archive_name = f"{crash_id}.uecrash"
    header_size = 3 + (4 + 260) * 2 + 4 + 4
    body = bytearray()
    for index, (name, data) in enumerate(files):
        body.extend(struct.pack("<i", index))
        body.extend(_ansi_field(name))
        body.extend(struct.pack("<i", len(data)))
        body.extend(data)
    uncompressed_size = header_size + len(body)
    header = (
        b"CR1"
        + _ansi_field(crash_id)
        + _ansi_field(archive_name)
        + struct.pack("<ii", uncompressed_size, len(files))
    )
    return zlib.compress(header + body)


def _write_agent_profile(tmp_path: Path, profile_id: str = "ue-crash-agent") -> None:
    profile_dir = tmp_path / "agent"
    profile_dir.mkdir(parents=True, exist_ok=True)
    (profile_dir / f"{profile_id}.json").write_text(
        json.dumps(
            {
                "id": profile_id,
                "name": "UE Crash Agent",
                "node_type_id": "agent_node",
                "fields": {
                    "provider_id": "",
                    "plugins": ["unreal-engine"],
                    "instruction": "Analyze Unreal Engine crashes from the supplied local path.",
                    "system_prompt": "",
                },
                "event_rules": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _crash_test_facade(tmp_path, monkeypatch):
    from src.web_backend import profile_storage, runtime_paths
    from src.web_backend.facade import WebBackendFacade

    monkeypatch.setattr(runtime_paths, "_get_runtime_root", lambda: str(tmp_path))
    monkeypatch.setattr(profile_storage, "get_workspace_root", lambda: str(tmp_path))
    facade = WebBackendFacade()
    monkeypatch.setattr(facade.core.graph_runtime, "_ensure_graph_runner", lambda _graph_id: None)
    monkeypatch.setattr(facade.core.graph_runtime, "_wake_graph_runner", lambda _graph_id: None)
    return facade


def test_ue_crash_receiver_extracts_archive_and_preserves_raw_payload(tmp_path, monkeypatch):
    _write_agent_profile(tmp_path)
    crash_id = "UECC-Windows-0123456789ABCDEF"
    payload = _ue_crash_payload(
        crash_id,
        [
            ("CrashContext.runtime-xml", b"<RuntimeProperties />"),
            ("XYJ.log", b"fatal error"),
        ],
    )

    response = TestClient(_crash_test_facade(tmp_path, monkeypatch).build()).post(
        "/api/ue/crashes/ue-crash-agent?AppID=UECrashReporter&AppVersion=5.7&AppEnvironment=Game&UploadType=crashreports&UserID=test",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["crash_id"] == crash_id
    assert body["profile_id"] == "ue-crash-agent"
    assert body["graph_id"] == "default"
    node_dir = Path(body["node_path"])
    crash_dir = node_dir / "ue-crash"
    assert node_dir.parent == tmp_path / "memories" / "default"
    assert (crash_dir / f"{crash_id}.uecrash").read_bytes() == payload
    assert (crash_dir / "files" / "CrashContext.runtime-xml").read_bytes() == b"<RuntimeProperties />"
    assert (crash_dir / "files" / "XYJ.log").read_bytes() == b"fatal error"
    manifest = json.loads((crash_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["file_count"] == 2
    assert manifest["query"]["UploadType"] == "crashreports"
    assert manifest["profile_id"] == "ue-crash-agent"
    from src.web_backend.node_config_service import node_config_service

    config = node_config_service.read_strict(str(node_dir / "config.json"))
    assert config["type_id"] == "agent_node"
    assert config["plugins"] == ["unreal-engine"]
    assert config["pending_count"] == 1
    pending_text = config["pending"][0]["payload"]["parts"][0]["text"]
    assert str(crash_dir) in pending_text


def test_ue_crash_receiver_rejects_unsafe_archive_file_name(tmp_path, monkeypatch):
    payload = _ue_crash_payload("UECC-Windows-BAD", [("../XYJ.log", b"bad")])

    response = TestClient(_crash_test_facade(tmp_path, monkeypatch).build()).post(
        "/api/ue/crashes?UploadType=crashreports&ProfileID=ue-crash-agent",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert "unsafe" in response.json()["detail"]
    graph_dir = tmp_path / "memories" / "default"
    assert not graph_dir.exists() or list(graph_dir.iterdir()) == []


def test_ue_crash_receiver_rejects_duplicate_crash_id(tmp_path, monkeypatch):
    _write_agent_profile(tmp_path)
    payload = _ue_crash_payload("UECC-Windows-DUPLICATE", [("XYJ.log", b"first")])
    client = TestClient(_crash_test_facade(tmp_path, monkeypatch).build())
    first = client.post(
        "/api/ue/crashes?UploadType=crashreports&ProfileID=ue-crash-agent",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )
    second = client.post(
        "/api/ue/crashes?UploadType=crashreports&ProfileID=ue-crash-agent",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert first.status_code == 200
    assert second.status_code == 409


def test_ue_crash_receiver_requires_profile_id(tmp_path, monkeypatch):
    payload = _ue_crash_payload("UECC-Windows-NO-PROFILE", [("XYJ.log", b"fatal")])

    response = TestClient(_crash_test_facade(tmp_path, monkeypatch).build()).post(
        "/api/ue/crashes?UploadType=crashreports",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ProfileID is required"


def test_ue_crash_receiver_rejects_unsafe_profile_id_in_path(tmp_path, monkeypatch):
    payload = _ue_crash_payload("UECC-Windows-BAD-PROFILE", [("XYJ.log", b"fatal")])

    response = TestClient(_crash_test_facade(tmp_path, monkeypatch).build()).post(
        "/api/ue/crashes/bad.profile?UploadType=crashreports",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "ProfileID contains unsupported characters"


def test_ue_crash_receiver_rejects_missing_agent_profile_without_creating_node(tmp_path, monkeypatch):
    payload = _ue_crash_payload("UECC-Windows-MISSING-PROFILE", [("XYJ.log", b"fatal")])

    response = TestClient(_crash_test_facade(tmp_path, monkeypatch).build()).post(
        "/api/ue/crashes?UploadType=crashreports&ProfileID=missing-profile",
        content=payload,
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 404
    graph_dir = tmp_path / "memories" / "default"
    assert not graph_dir.exists() or list(graph_dir.iterdir()) == []


def test_unreal_engine_plugin_bundles_remote_control_tools():
    from nodes.agent_plugin_loader import resolve_plugin_capabilities

    capabilities = resolve_plugin_capabilities(["unreal-engine"])

    assert capabilities.tools == ()
    assert tuple(item.name for item in capabilities.tool_definitions) == (
        "cancer_control",
        "ue_remote_control",
    )
    assert tuple(item.source_name for item in capabilities.tool_definitions) == (
        "cancer_control",
        "ue_remote_control",
    )


def test_plugin_server_api_loader_registers_plugin_route(tmp_path):
    from fastapi import FastAPI
    from nodes.agent_plugin_api_loader import register_installed_plugin_apis

    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "agentpark.plugin.json").write_text(
        json.dumps({"id": "demo", "serverApi": ["./api.py"]}),
        encoding="utf-8",
    )
    (plugin_dir / "api.py").write_text(
        "def get_api_routes(context):\n"
        "    def probe():\n"
        "        return {'plugin_id': context.plugin_id}\n"
        "    return [{'method': 'get', 'path': '/api/demo/probe', 'handler': probe}]\n",
        encoding="utf-8",
    )
    app = FastAPI()

    registrations = register_installed_plugin_apis(
        app,
        plugin_root=str(tmp_path / "plugins"),
        runtime_root=str(tmp_path),
        resource_root=str(tmp_path),
    )

    assert [(item.plugin_id, item.method, item.path) for item in registrations] == [
        ("demo", "get", "/api/demo/probe")
    ]
    assert TestClient(app).get("/api/demo/probe").json() == {"plugin_id": "demo"}


def test_plugin_server_api_loader_rejects_core_route_conflict(tmp_path):
    import pytest
    from fastapi import FastAPI
    from nodes.agent_plugin_api_loader import PluginApiLoadError, register_installed_plugin_apis

    plugin_dir = tmp_path / "plugins" / "demo"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "agentpark.plugin.json").write_text(
        json.dumps({"id": "demo", "serverApi": ["./api.py"]}),
        encoding="utf-8",
    )
    (plugin_dir / "api.py").write_text(
        "def get_api_routes(context):\n"
        "    def probe():\n"
        "        return {'ok': True}\n"
        "    return [{'method': 'get', 'path': '/api/existing', 'handler': probe}]\n",
        encoding="utf-8",
    )
    app = FastAPI()

    @app.get("/api/existing")
    def existing():
        return {"core": True}

    with pytest.raises(PluginApiLoadError, match="conflicts"):
        register_installed_plugin_apis(
            app,
            plugin_root=str(tmp_path / "plugins"),
            runtime_root=str(tmp_path),
            resource_root=str(tmp_path),
        )
