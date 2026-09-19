from __future__ import annotations

import secrets
import time
from collections import deque
from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import HTTPException, Request


COOKIE = "agentpark_portal_session"
SESSION_SECONDS = 3 * 24 * 60 * 60
# A browser login may outlive individual Board connections. Devices accept
# tickets for at most one hour; reconnecting uses the existing login cookie.
BOARD_CONNECTION_SECONDS = 60 * 60


@dataclass
class PortalSession:
    expires_at: int
    browser_ids: set[str]


class PortalAuth:
    def __init__(self, password: str):
        if password and len(password) < 8:
            raise ValueError("Portal password must contain at least 8 characters.")
        self.password = password
        self.sessions: dict[str, PortalSession] = {}
        self.attempts: dict[str, deque[float]] = {}

    @staticmethod
    def require_origin(request) -> None:
        origin = request.headers.get("origin")
        if not origin or urlsplit(origin).netloc != request.headers.get("host"):
            raise HTTPException(403, "Same-origin portal request required.")

    def login(self, password: str, address: str) -> str:
        if not self.password:
            raise HTTPException(503, "Portal login is not configured on the coordinator.")
        now = time.time()
        self.attempts = {key: values for key, values in self.attempts.items() if values and now - values[-1] < 60}
        if address not in self.attempts and len(self.attempts) >= 1000:
            raise HTTPException(429, "Login rate limit exceeded.")
        attempts = self.attempts.setdefault(address, deque())
        while attempts and now - attempts[0] > 60:
            attempts.popleft()
        if len(attempts) >= 5:
            raise HTTPException(429, "Too many login attempts. Try again in a minute.")
        attempts.append(now)
        if not secrets.compare_digest(password.encode(), self.password.encode()):
            raise HTTPException(401, "Incorrect portal password.")
        self.sessions = {key: value for key, value in self.sessions.items() if value.expires_at > now}
        if len(self.sessions) >= 100:
            raise HTTPException(429, "Too many active portal sessions.")
        token = secrets.token_urlsafe(32)
        self.sessions[token] = PortalSession(int(now) + SESSION_SECONDS, set())
        return token

    def require_session(self, request) -> PortalSession:
        token = request.cookies.get(COOKIE, "")
        session = self.sessions.get(token)
        if session is None or session.expires_at <= time.time():
            raise HTTPException(401, "Portal session expired. Please sign in.")
        return session
