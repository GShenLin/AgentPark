"""Authenticated, short-lived TURN credentials; never persisted by clients."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import time
from dataclasses import dataclass, field

from pydantic import BaseModel, ConfigDict, Field, field_validator


TURN_URL = re.compile(r"^turns?:(?:\[[0-9a-fA-F:]+\]|[a-zA-Z0-9.-]+):([0-9]{1,5})\?transport=(tcp|udp)$")
CREDENTIAL_SECONDS = 3600
REFRESH_SECONDS = 600


def validate_turn_url(url: str) -> str:
    match = TURN_URL.fullmatch(url)
    if not match or not 1 <= int(match[1]) <= 65535 or (url.startswith("turns:") and match[2] != "tcp"):
        raise ValueError("TURN URLs must specify a host, port and supported tcp/udp transport.")
    return url


class TurnServer(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    urls: list[str] = Field(min_length=1, max_length=4)
    username: str = Field(min_length=1, max_length=200)
    credential: str = Field(min_length=1, max_length=200, repr=False)

    @field_validator("urls")
    @classmethod
    def validate_urls(cls, values: list[str]) -> list[str]:
        return [validate_turn_url(value) for value in values]


class IceLease(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, hide_input_in_errors=True)
    ice_servers: list[TurnServer] = Field(max_length=4)
    expires_at: int

    def require_fresh(self) -> None:
        if self.expires_at <= time.time():
            raise ValueError("Connection credentials expired; reconnect to the coordinator.")


@dataclass(frozen=True)
class TurnIssuer:
    urls: tuple[str, ...] = ()
    secret: str = field(default="", repr=False)

    def __post_init__(self):
        if bool(self.urls) != bool(self.secret) or len(self.urls) > 4:
            raise ValueError("Configure both TURN URLs and their shared authentication secret.")
        if self.secret and len(self.secret) < 32:
            raise ValueError("TURN shared secret must contain at least 32 characters.")
        for url in self.urls:
            validate_turn_url(url)

    @classmethod
    def from_environment(cls) -> "TurnIssuer":
        urls = json.loads(os.environ.get("AGENTPARK_TURN_URLS", "[]"))
        if not isinstance(urls, list) or any(not isinstance(url, str) for url in urls):
            raise ValueError("AGENTPARK_TURN_URLS must be a JSON array of TURN URLs.")
        return cls(tuple(urls), os.environ.get("AGENTPARK_TURN_SECRET", ""))

    def issue(self, principal: str, *, expires_at: int | None = None) -> IceLease:
        if not re.fullmatch(r"[0-9a-f]{64}", principal):
            raise ValueError("TURN credentials require an authenticated peer identity.")
        expiry = min(int(time.time()) + CREDENTIAL_SECONDS, expires_at) if expires_at else int(time.time()) + CREDENTIAL_SECONDS
        servers = []
        if self.urls:
            username = f"{expiry}:{principal}"
            credential = base64.b64encode(hmac.new(self.secret.encode(), username.encode(), hashlib.sha1).digest()).decode()
            servers = [TurnServer(urls=list(self.urls), username=username, credential=credential)]
        return IceLease(ice_servers=servers, expires_at=expiry)
