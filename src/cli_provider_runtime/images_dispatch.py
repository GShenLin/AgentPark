"""Native Images API forwarding; no conversational conversion or local files."""
from typing import Any
from urllib.parse import urlsplit

from src.provider_auth.credentials import resolve_provider_request_credentials

from .gateway_dispatch import GatewayDispatchResult
from .http_transport import UpstreamHttpError, open_json_request, read_json_response
from .http_transport import resolve_upstream_request_policy
from .http_transport import copy_response_lines


IMAGE_ENDPOINTS = {
    "images_generations": "images/generations",
    "images_edits": "images/edits",
}


def dispatch_images(config: dict[str, Any], payload: dict[str, Any], protocol: str) -> GatewayDispatchResult:
    if protocol not in IMAGE_ENDPOINTS:
        raise ValueError(f"Unsupported Images protocol: {protocol!r}.")
    if config.get("type") != "openai" or "image_generation" not in config.get("supportmode", []):
        raise ValueError("Provider does not support the native OpenAI Images API.")
    model = config.get("model")
    if not isinstance(model, str) or not model.strip():
        raise ValueError("Image Provider requires a model.")
    if not isinstance(payload.get("prompt"), str) or not payload["prompt"].strip():
        raise ValueError("Images request requires a non-empty prompt.")
    if "stream" in payload and not isinstance(payload["stream"], bool):
        raise ValueError("Images stream must be a boolean.")
    if protocol == "images_edits":
        images = payload.get("images")
        if not isinstance(images, list) or not images:
            raise ValueError("JSON image edits require a non-empty images array of image_url or file_id objects.")
        for item in images:
            _validate_reference(item)
    request = {**payload, "model": model}
    response = _open_images(config, request, IMAGE_ENDPOINTS[protocol], force_refresh=False)
    if payload.get("stream", False):
        return GatewayDispatchResult(
            status=response.status, content_type=response.headers.get("content-type", "text/event-stream"),
            stream=copy_response_lines(response),
        )
    return GatewayDispatchResult(
        status=response.status, content_type="application/json", json_body=read_json_response(response),
    )


def _validate_reference(item: object) -> None:
    if not isinstance(item, dict):
        raise ValueError("Each image reference must be an object.")
    if set(item) == {"file_id"} and isinstance(item["file_id"], str) and item["file_id"].strip():
        return
    if set(item) == {"image_url"} and isinstance(item["image_url"], str):
        url = item["image_url"]
        parsed = urlsplit(url)
        if (parsed.scheme in {"https", "http"} and parsed.netloc) or url.startswith("data:image/"):
            return
    raise ValueError("Image references require a remote image_url, image data URL, or file_id; local paths are not accepted.")


def _open_images(config: dict[str, Any], payload: dict[str, Any], endpoint: str, *, force_refresh: bool):
    credentials = resolve_provider_request_credentials(config, force_refresh=force_refresh)
    # Generation is not idempotent. Do not inherit the chat transport's automatic
    # retries after a timeout or server error, which could generate duplicate images.
    policy = resolve_upstream_request_policy({**config, "maxRetries": 0})
    try:
        return open_json_request(
            url=f"{credentials.base_url.rstrip('/')}/{endpoint}",
            headers={**credentials.headers, "Accept": "text/event-stream" if payload.get("stream", False) else "application/json"},
            payload=payload, policy=policy,
            stream=payload.get("stream", False),
        )
    except UpstreamHttpError as exc:
        if exc.status == 401 and config.get("authMode") in {"codex", "oauth"} and not force_refresh:
            return _open_images(config, payload, endpoint, force_refresh=True)
        raise
