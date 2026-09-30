"""MiniMax Code's node-owned BYOK configuration and advertised ACP selections."""
from __future__ import annotations

import os
from pathlib import Path
from urllib.parse import unquote

import yaml

from src.harness.reasoning_config import reasoning_options
from src.harness.config import CliRunRequest
from src.harness.responses_gateway import GatewayLease
from .cli_session import write_json


PROVIDER_ID = "custom_provider:agentpark"


def permission_selection(control: dict, mode: str) -> str:
    options = control.get("configOptions")
    if not isinstance(options, list):
        raise ValueError("MiniMax Code did not advertise session configOptions.")
    controls = [item for item in options if isinstance(item, dict) and item.get("id") == "permissionMode"]
    if len(controls) != 1 or controls[0].get("type") != "select":
        raise ValueError("MiniMax Code must advertise a permissionMode select control.")
    choices = controls[0].get("options")
    if not isinstance(choices, list) or sum(isinstance(item, dict) and item.get("value") == mode for item in choices) != 1:
        raise ValueError("MiniMax Code did not advertise the requested permission mode.")
    return mode


def configure_home(request: CliRunRequest, lease: GatewayLease, env: dict[str, str]) -> Path:
    home = request.state_dir / "home"
    # 0.4.12's SQLite backup uses Win32 MAX_PATH even when Node supports long paths.
    backup = home / "v2" / "sqlite" / "backups" / (
        "runtime-state-before-v2-migration-0000000000000-00000000-0000-4000-8000-000000000000.sqlite")
    if os.name == "nt" and len(str(backup).encode("utf-16-le")) // 2 >= 260:
        raise ValueError("MiniMax Code 0.4.12 SQLite backup exceeds Windows MAX_PATH. "
                         f"Use a shorter AgentPark workspace/node directory: {home}")
    home.mkdir(exist_ok=True)
    path = home / "config.yaml"
    config = yaml.safe_load(path.read_text(encoding="utf-8")) if path.exists() else {}
    if not isinstance(config, dict):
        raise ValueError("MiniMax Code config must be an object.")
    custom = config.get("custom_provider", {})
    if not isinstance(custom, dict) or not isinstance(custom.get("agentpark", {}), dict):
        raise ValueError("Invalid MiniMax Code custom_provider configuration.")
    models = custom.get("agentpark", {}).get("models", {})
    if not isinstance(models, dict) or any(not isinstance(value, dict) for value in models.values()):
        raise ValueError("MiniMax Code models must be an object of model descriptors.")
    provider = request.binding.request_config()
    limits = {}
    for source, target in (("modelContextWindowTokens", "context"), ("maxTokens", "output")):
        value = provider.get(source)
        if value is not None:
            if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
                raise ValueError(f"MiniMax Code requires a positive integer {source}.")
            limits[target] = value
    efforts = reasoning_options(provider)
    model = {"name": request.binding.model_id, "tool_call": True}
    if limits:
        model["limit"] = limits
    if efforts:
        model["reasoning"] = True
        model["thinking"] = {"effortOptions": efforts}
        if request.reasoning_effort:
            model["thinking"]["defaultEffort"] = request.reasoning_effort
    # Historical descriptors remain resolvable when the native session is resumed.
    # The current gateway lease pins every request to the selected Provider/Model.
    models = {**models, request.binding.model_id: model}
    config.update({
        "custom_provider": {"agentpark": {
            "kind": "custom", "enabled": True, "name": "AgentPark", "api": "openai-responses",
            "options": {"baseURL": lease.base_url, "apiKey": lease.token}, "models": models,
        }},
        "defaultModel": f"{PROVIDER_ID}/{request.binding.model_id}",
        "defaultLightModel": f"{PROVIDER_ID}/{request.binding.model_id}",
        # AgentPark owns node names; background native title generation must not
        # introduce an unobserved model request after the foreground turn ends.
        "sessionTitle": {"enabled": False},
        "telemetry": {"enabled": False, "metrics": False, "diagnostics": False},
    })
    write_json(path, config)  # JSON is valid YAML; the runtime can rewrite it as YAML.
    env["MINIMAX_DATA_DIR"] = str(home)
    env["MAVIS_DATA_DIR"] = str(home)
    return home


def model_selection(control: dict, model_id: str) -> str:
    options = control.get("configOptions")
    if not isinstance(options, list):
        raise ValueError("MiniMax Code did not advertise session configOptions.")
    matches = []
    for option in options:
        if not isinstance(option, dict) or option.get("id") != "model":
            continue
        if option.get("type") != "select" or not isinstance(option.get("options"), list):
            raise ValueError("MiniMax Code model control must be a select.")
        for item in option["options"]:
            if not isinstance(item, dict) or not isinstance(item.get("value"), str):
                raise ValueError("Invalid MiniMax Code model selection.")
            parts = item["value"].split(":")
            if len(parts) not in {4, 5} or parts[0] != "m":
                raise ValueError("Invalid MiniMax Code model selection encoding.")
            if (unquote(parts[1]), unquote(parts[2])) == (PROVIDER_ID, model_id):
                if parts[3:] == ["u"] or (len(parts) == 5 and parts[3] == "v"):
                    matches.append(item["value"])
    if len(matches) != 1:
        raise ValueError("MiniMax Code must advertise exactly one selection for the bound model.")
    return matches[0]
