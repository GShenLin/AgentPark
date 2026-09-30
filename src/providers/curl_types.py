"""Response and error contracts shared by the existing curl transport."""
import json
from dataclasses import dataclass, field

from .provider_errors import ProviderTransportError


class CurlTransportError(ProviderTransportError):
    pass


class CurlHttpError(CurlTransportError):
    def __init__(self, response):
        self.status_code = response.status_code
        self.content = response.content
        self.headers = response.headers
        super().__init__(f"HTTP {self.status_code}: {response.body[:2000]}")


@dataclass(frozen=True)
class CurlResponse:
    body: str
    status_code: int
    headers: dict[str, str] = field(default_factory=dict)
    raw_body: bytes | None = field(default=None, repr=False)

    @property
    def content(self) -> bytes:
        return self.raw_body if self.raw_body is not None else self.body.encode("utf-8")

    def json(self):
        return json.loads(self.content)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise CurlHttpError(self)
        return self
