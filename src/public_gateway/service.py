from __future__ import annotations

from itertools import chain
from typing import Any

from src.cli_provider_runtime.gateway_dispatch import GatewayDispatchResult
from src.cli_provider_runtime.gateway_dispatch import dispatch_chat_completions
from src.cli_provider_runtime.gateway_dispatch import dispatch_messages
from src.cli_provider_runtime.gateway_dispatch import dispatch_responses
from src.cli_provider_runtime.images_dispatch import dispatch_images

from .store import PublicGatewayStore
from .usage_stats import PublicGatewayUsageStore
from .protocols import IMAGE_PROTOCOLS


class PublicGatewayService:
    def __init__(self, workspace_root: str | None = None) -> None:
        self.store = PublicGatewayStore(workspace_root)
        self.usage_store = PublicGatewayUsageStore(self.store.workspace_root)

    @property
    def workspace_root(self) -> str:
        return self.store.workspace_root

    def settings(self) -> dict[str, Any]:
        return self.store.snapshot()

    def usage(self, date_text: str) -> dict[str, Any]:
        return self.usage_store.aggregate(date_text)

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.store.update_settings(payload)
        return self.settings()

    def replace_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.store.replace_models(payload)
        return self.settings()

    def create_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        created = self.store.create_key(payload)
        return {"created": created, "keys": self.store.list_keys()}

    def delete_key(self, key_id: str) -> dict[str, Any]:
        self.store.delete_key(key_id)
        return {"deleted": True, "keys": self.store.list_keys()}

    def authorize(self, authorization: str, x_api_key: str) -> bool:
        config = self.store.load_config()
        if not config["requireApiKey"]:
            return True
        bearer = ""
        scheme, separator, value = str(authorization or "").partition(" ")
        if separator and scheme.lower() == "bearer":
            bearer = value.strip()
        return self.store.authenticate(bearer or str(x_api_key or "").strip())

    def models(self) -> dict[str, Any]:
        return {
            "object": "list",
            "data": [
                {
                    "id": item["id"],
                    "object": "model",
                    "created": 0,
                    "owned_by": "agentpark",
                    "metadata": {
                        "providerId": item["providerId"],
                        "protocols": item["protocols"],
                    },
                }
                for item in self.store.list_public_models()
            ],
        }

    def route_metadata(self, protocol: str, model_id: str) -> dict[str, Any]:
        model, provider_config = self.store.resolve_model(model_id, protocol)
        return {
            "providerId": model["providerId"],
            "accountId": model["accountId"] or None,
            "upstreamModel": str(provider_config.get("model") or ""),
            "providerType": str(provider_config.get("type") or ""),
            "authMode": str(provider_config.get("authMode") or ""),
        }

    def dispatch(
        self,
        protocol: str,
        payload: dict[str, Any],
    ) -> GatewayDispatchResult:
        model_id = str(payload.get("model") or "").strip()
        if not model_id:
            raise ValueError("Gateway request requires a model.")
        _model, provider_config = self.store.resolve_model(model_id, protocol)
        if protocol == "responses":
            result = dispatch_responses(provider_config, payload)
        elif protocol == "chat_completions":
            result = dispatch_chat_completions(provider_config, payload)
        elif protocol == "messages":
            result = dispatch_messages(provider_config, payload)
        elif protocol in IMAGE_PROTOCOLS:
            result = dispatch_images(provider_config, payload, protocol)
        else:
            raise ValueError(f"Unsupported Gateway protocol: {protocol!r}.")
        return _prime_stream(result)

    def test(self, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise ValueError("Gateway test payload must be an object.")
        protocol = str(payload.get("protocol") or "responses").strip()
        model = str(payload.get("model") or "").strip()
        prompt = str(payload.get("prompt") or "Reply with exactly: AgentPark gateway ready.").strip()
        if protocol == "responses":
            request = {"model": model, "input": prompt, "stream": False}
        elif protocol == "chat_completions":
            request = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            }
        elif protocol == "messages":
            request = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "max_tokens": 128,
                "stream": False,
            }
        elif protocol in IMAGE_PROTOCOLS:
            request = {"model": model, "prompt": prompt, "stream": False}
            if protocol == "images_edits":
                request["images"] = payload.get("images")
        else:
            raise ValueError(f"Unsupported Gateway protocol: {protocol!r}.")
        result = self.dispatch(protocol, request)
        if result.json_body is None:
            raise RuntimeError("Gateway test unexpectedly returned a stream.")
        return {
            "ok": 200 <= result.status < 300,
            "status": result.status,
            "protocol": protocol,
            "model": model,
            "response": result.json_body,
        }


def _prime_stream(result: GatewayDispatchResult) -> GatewayDispatchResult:
    if result.stream is None:
        return result
    iterator = iter(result.stream)
    try:
        first = next(iterator)
    except StopIteration:
        stream = ()
    else:
        stream = chain((first,), iterator)
    return GatewayDispatchResult(
        status=result.status,
        content_type=result.content_type,
        stream=stream,
    )


__all__ = ["PublicGatewayService"]
