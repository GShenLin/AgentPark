from __future__ import annotations


class ProviderError(RuntimeError):
    """Base class for provider-layer failures."""


class ProviderConfigError(ProviderError, ValueError):
    """Provider configuration is invalid or incomplete."""


class ProviderInputError(ProviderError, ValueError):
    """User or upstream input cannot be sent to the provider."""


class ProviderProtocolError(ProviderError):
    """Provider response shape or stream protocol is invalid."""


class ProviderTransportError(ProviderError):
    """Network, curl, process, or transport-level failure."""


class ProviderHttpError(ProviderError):
    """Provider returned a non-success HTTP status."""

    def __init__(self, status_code: int, response_body: str, *, message_prefix: str = "HTTP"):
        self.status_code = int(status_code or 0)
        self.response_body = str(response_body or "")
        super().__init__(f"{message_prefix} {self.status_code}: {self.response_body}")


class ProviderImageAttachmentError(ProviderInputError):
    pass
