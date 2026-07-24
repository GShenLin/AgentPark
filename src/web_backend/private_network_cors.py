from __future__ import annotations

from collections.abc import Sequence

from starlette.datastructures import Headers
from starlette.middleware.cors import CORSMiddleware
from starlette.responses import Response
from starlette.types import ASGIApp


class PrivateNetworkCORSMiddleware(CORSMiddleware):
    """CORS middleware with explicit Private Network Access preflight support."""

    def __init__(
        self,
        app: ASGIApp,
        allow_origins: Sequence[str] = (),
        allow_methods: Sequence[str] = ("GET",),
        allow_headers: Sequence[str] = (),
        allow_credentials: bool = False,
        allow_origin_regex: str | None = None,
        expose_headers: Sequence[str] = (),
        max_age: int = 600,
        allow_private_network: bool = False,
    ) -> None:
        super().__init__(
            app=app,
            allow_origins=allow_origins,
            allow_methods=allow_methods,
            allow_headers=allow_headers,
            allow_credentials=allow_credentials,
            allow_origin_regex=allow_origin_regex,
            expose_headers=expose_headers,
            max_age=max_age,
        )
        self.allow_private_network = allow_private_network

    def preflight_response(self, request_headers: Headers) -> Response:
        response = super().preflight_response(request_headers)
        private_network_requested = (
            request_headers.get("access-control-request-private-network", "").casefold() == "true"
        )
        if self.allow_private_network and private_network_requested:
            response.headers["Access-Control-Allow-Private-Network"] = "true"
        return response


__all__ = ["PrivateNetworkCORSMiddleware"]
