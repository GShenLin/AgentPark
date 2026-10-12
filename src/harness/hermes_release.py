"""Official Hermes release identity (calendar tag and Python package version are distinct)."""
from __future__ import annotations

from src.providers.curl_transport import CurlHttpTransport
from dataclasses import dataclass
import re
import tomllib
from typing import Literal

from .updates import version_key

REPOSITORY = "https://github.com/NousResearch/hermes-agent.git"
RELEASES_URL = "https://github.com/NousResearch/hermes-agent/releases"


@dataclass(frozen=True)
class HermesRelease:
    tag: str
    version: str
    layout: Literal["venv", "pm"] = "venv"


def read_url(url: str) -> bytes:
    request = dict(url=url, headers={"User-Agent": "AgentPark-Harness", "Accept": "text/plain"})
    response = CurlHttpTransport().request(**request, timeout_sec=20, max_response_bytes=2 * 1024 * 1024 + 1).raise_for_status()
    data = response.content[:2 * 1024 * 1024 + 1]
    if len(data) > 2 * 1024 * 1024:
        raise ValueError("Hermes release metadata exceeds 2 MiB.")
    return data


def latest_release() -> HermesRelease:
    # GitHub's documented latest-release link selects the published release without
    # the REST API's anonymous IP quota. Inspect the redirect, never scrape HTML
    # or infer a release from the newest Git tag (which may be unpublished).
    response = CurlHttpTransport().request(
        url=f"{RELEASES_URL}/latest", method="HEAD", follow_redirects=False,
        headers={"User-Agent": "AgentPark-Harness"}, timeout_sec=20,
        max_response_bytes=64 * 1024,
    ).raise_for_status()
    if response.status_code != 302:
        raise ValueError(f"Expected a Hermes latest-release redirect, got HTTP {response.status_code}.")
    match = re.fullmatch(re.escape(RELEASES_URL) + r"/tag/(v[0-9]+\.[0-9]+\.[0-9]+)",
                         response.headers.get("location", ""))
    if match is None:
        raise ValueError("Invalid Hermes release redirect: expected an official repository release tag.")
    tag = match[1]
    manifest = tomllib.loads(read_url(
        f"https://raw.githubusercontent.com/NousResearch/hermes-agent/{tag}/pyproject.toml").decode("utf-8"))
    project = manifest.get("project")
    if not isinstance(project, dict) or project.get("name") != "hermes-agent":
        raise ValueError("Unexpected Hermes release package.")
    version_key(project.get("version"))
    if project["version"] == "0.0.0":
        # PM releases declare identity through the admitted SemVer release tag,
        # then persist it with the upstream install-stamp writer. Calendar tags
        # belong to the older package-version contract and cannot supply it.
        if not re.fullmatch(r"v(0|[1-9][0-9]{0,2})\.[0-9]+\.[0-9]+", tag):
            raise ValueError("Hermes PM releases require a semantic version release tag.")
        version_key(tag[1:])
        return HermesRelease(tag, tag[1:], "pm")
    return HermesRelease(tag, project["version"])
