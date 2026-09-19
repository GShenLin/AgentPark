"""Observe requests rejected before a Gateway handler can record them."""
import time

from fastapi import FastAPI

from .access_log import PublicGatewayAccessLog, request_fields, new_request_id


def register_request_diagnostics(app: FastAPI, log: PublicGatewayAccessLog) -> None:
    @app.middleware("http")
    async def record_unhandled_gateway_request(request, call_next):
        started_at = time.perf_counter()
        response = await call_next(request)
        if request.url.path.startswith("/v1/") and "x-request-id" not in response.headers:
            # A route mismatch, method mismatch or JSON validation error bypasses
            # dispatch. Never record raw bodies, prompts, image data or credentials.
            request_id = new_request_id()
            log.record(
                "request_rejected", **request_fields(request, request_id),
                status=response.status_code, reason="rejected_before_dispatch",
                durationMs=round((time.perf_counter() - started_at) * 1000),
            )
            response.headers["x-request-id"] = request_id
        return response
