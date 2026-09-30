"""Official Hermes release identity (calendar tag and Python package version are distinct)."""
from __future__ import annotations

from src.providers.curl_transport import CurlHttpTransport, CurlHttpError, CurlTransportError
from dataclasses import dataclass
import json
import re
import tomllib

from .updates import version_key

REPOSITORY = "https://github.com/NousResearch/hermes-agent.git"


@dataclass(frozen=True)
class HermesRelease:
    tag: str
    version: str


def read_url(url: str) -> bytes:
    request = dict(url=url, headers={"User-Agent": "AgentPark-Harness", "Accept": "application/json"})
    response = CurlHttpTransport().request(**request, timeout_sec=20, max_response_bytes=2 * 1024 * 1024 + 1).raise_for_status()
    data = response.content[:2 * 1024 * 1024 + 1]
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Hermes release metadata exceeds 2 MiB.")
    return data


def latest_release() -> HermesRelease:
    data = json.loads(read_url("https://api.github.com/repos/NousResearch/hermes-agent/releases/latest"))
    if not isinstance(data, dict) or data.get("draft") is not False or data.get("prerelease") is not False:
        raise ValueError("Expected a published stable Hermes release.")
    tag = data.get("tag_name")
    if not isinstance(tag, str) or not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+", tag):
        raise ValueError("Invalid Hermes release tag.")
    manifest = tomllib.loads(read_url(
        f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{tag}/pyproject.toml").decode("utf-8"))
    project = manifest.get("project")
    if not isinstance(project, dict) or project.get("name") != "hermes-agent":
        raise ValueError("Unexpected Hermes release package.")
    version_key(project.get("version"))
    return HermesRelease(tag, project["version"])
