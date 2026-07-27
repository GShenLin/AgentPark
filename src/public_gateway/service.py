from __future__ import annotations

from itertools import chain
from typing import Any

from src.cli_provider_runtime.gateway_dispatch import GatewayDispatchResult
from src.cli_provider_runtime.gateway_dispatch import dispatch_chat_completions
from src.cli_provider_runtime.gateway_dispatch import dispatch_messages
from src.cli_provider_runtime.gateway_dispatch import dispatch_responses

from .store import PublicGatewayStore


class PublicGatewayService:
    def __init__(self, workspace_root: str | None = None) -> None:
        self.store = PublicGatewayStore(workspace_root)

    def settings(self) -> dict[str, Any]:
        return self.store.snapshot()

    def update_options(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.store.update_options(payload)
        return self.settings()

    def upsert_model(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.store.upsert_model(payload)
        return self.settings()

    def delete_model(self, model_id: str) -> dict[str, Any]:
        self.store.delete_model(model_id)
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
