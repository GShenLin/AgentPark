from src.providers.provider_errors import ProviderHttpError
from src.providers.provider_errors import ProviderTransportError


class OpenAIHttpError(ProviderHttpError):
    pass


class OpenAITransportError(ProviderTransportError):
    pass
