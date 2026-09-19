from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from src.cli_provider_runtime.http_transport import UpstreamHttpError
from src.public_gateway.service import PublicGatewayService


class PublicGatewayApiDomain:
    def __init__(self) -> None:
        self.service = PublicGatewayService()

    def get_settings(self) -> dict[str, Any]:
        return self.service.settings()

    def get_usage(self, date_text: str) -> dict[str, Any]:
        return self._management_call(self.service.usage, date_text)

    def update_settings(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._management_call(self.service.update_settings, payload)

    def replace_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._management_call(self.service.replace_models, payload)

    def create_key(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._management_call(self.service.create_key, payload)

    def delete_key(self, key_id: str) -> dict[str, Any]:
        return self._management_call(self.service.delete_key, key_id)

    def test(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._management_call(self.service.test, payload)

    @staticmethod
    def _management_call(function, *args):
        try:
            return function(*args)
        except UpstreamHttpError as exc:
            detail = exc.body.decode("utf-8", errors="replace")
            raise HTTPException(status_code=502, detail=f"Upstream HTTP {exc.status}: {detail}") from exc
        except KeyError as exc:
            message = str(exc.args[0]) if exc.args else str(exc)
            raise HTTPException(status_code=404, detail=message) from exc
        except (ValueError, RuntimeError) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc


__all__ = ["PublicGatewayApiDomain"]
