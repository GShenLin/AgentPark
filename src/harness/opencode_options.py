"""Read native ACP select controls without sending a prompt or altering node sessions."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
import tempfile
import time

from .acp_client import AcpClient
from .install_manager import command_argv, install_root, runtime_lease
from .adapters.opencode_config import select_option


@contextmanager
def discovery_directory(root: Path):
    temporary = tempfile.TemporaryDirectory(prefix="options-", dir=root)
    path = Path(temporary.name)
    try:
        yield path
    finally:
        if path.resolve() != path.absolute() or path.parent.resolve() != root.resolve():
            raise ValueError("OpenCode discovery directory escaped its installation root.")
        # Windows can retain a SQLite mapping briefly after the process exits.
        # Wait only for the observed sharing violation; all other failures surface immediately.
        deadline = time.monotonic() + 3
        while True:
            try:
                temporary.cleanup()
                break
            except PermissionError as exc:
                if getattr(exc, "winerror", None) != 32 or time.monotonic() >= deadline:
                    raise
                time.sleep(0.05)


def options(control: dict, config_id: str, *, optional: bool = False) -> list[dict]:
    controls = control.get("configOptions")
    if not isinstance(controls, list):
        raise ValueError("OpenCode did not advertise ACP configOptions.")
    matches = [item for item in controls if isinstance(item, dict) and item.get("id") == config_id]
    if not matches and optional:
        return []
    if len(matches) != 1 or matches[0].get("type") != "select":
        raise ValueError(f"OpenCode did not advertise one selectable {config_id} option.")
    result = []
    def append(items):
        if not isinstance(items, list):
            raise ValueError(f"Invalid OpenCode {config_id} options.")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError(f"Invalid OpenCode {config_id} option.")
            if "group" in item:
                append(item.get("options"))
                continue
            value, label = item.get("value"), item.get("name")
            if not isinstance(value, str) or not value or not isinstance(label, str) or not label:
                raise ValueError(f"Invalid OpenCode {config_id} option value or name.")
            result.append({"value": value, "label": label})
    append(matches[0].get("options"))
    if len({item["value"] for item in result}) != len(result):
        raise ValueError(f"Duplicate OpenCode {config_id} options.")
    return result


def configuration_options(*, model: str, agent: str, working_path: str = "") -> dict:
    with runtime_lease("opencode"):
        root = install_root("opencode")
        root.mkdir(parents=True, exist_ok=True)
        # Read the target project's native config, but keep discovery sessions ephemeral.
        with discovery_directory(root) as temporary:
            cwd = Path(working_path).expanduser().resolve() if working_path else Path(temporary)
            if not cwd.is_dir():
                raise ValueError(f"OpenCode working_path does not exist: {cwd}")
            client = AcpClient([*command_argv("opencode"), "acp"], cwd=str(cwd),
                env={**os.environ, "OPENCODE_DB": str(Path(temporary) / "catalog.db")},
                timeout=45, cancel_source=None, on_update=lambda _: None)
            try:
                init = client.request("initialize", {"protocolVersion": 1, "clientCapabilities": {},
                    "clientInfo": {"name": "agentpark", "version": "1"}})
                if init.get("protocolVersion") != 1:
                    raise ValueError("OpenCode requires ACP protocol version 1.")
                control = client.request("session/new", {"cwd": str(cwd), "mcpServers": []})
                session = control.get("sessionId")
                if not isinstance(session, str) or not session:
                    raise ValueError("OpenCode did not create a discovery session.")
                selection_error = ""
                for key, value in (("mode", agent), ("model", model)):
                    choices = options(control, key)
                    if not any(item["value"] == value for item in choices):
                        selection_error = f"OpenCode {key} is unavailable: {value}"
                        break
                    control = client.request("session/set_config_option", {"sessionId": session,
                        "configId": key, "value": select_option(control, key, value)})
                result = {"native_agent": options(control, "mode"), "native_model": options(control, "model"),
                          "native_effort": options(control, "effort", optional=True) if not selection_error else [],
                          "selection_error": selection_error}
                client.request("session/close", {"sessionId": session})
                return result
            finally:
                client.close()
