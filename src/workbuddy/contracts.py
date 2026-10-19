"""Public gateway contracts. Extra upstream fields never cross into the UI."""
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator


class PublicModel(BaseModel):
    model_config = ConfigDict(strict=True, extra="ignore")


class AccountStatus(PublicModel):
    connected: bool
    account: str
    models: int = Field(ge=0)


class ConnectionStatus(PublicModel):
    connected: bool


class Login(PublicModel):
    loginId: str = Field(min_length=16, max_length=128)
    authorizationUrl: str

    @field_validator("authorizationUrl")
    @classmethod
    def official_url(cls, value: str) -> str:
        url = urlsplit(value)
        if (url.scheme != "https" or url.netloc not in {"www.workbuddy.ai", "www.codebuddy.ai"}
                or url.username or url.password):
            raise ValueError("Unexpected WorkBuddy authorization origin")
        return value


class Billing(PublicModel):
    label: str
    multiplier: float | None
    free: bool
    promotionEndsAt: str
    promotionText: str


class Model(PublicModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    description: str
    contextWindow: int = Field(gt=0)
    maxTokens: int = Field(gt=0)
    supportsImages: bool
    reasoningEfforts: list[str]
    billing: Billing


class Catalog(PublicModel):
    data: list[Model]

    @field_validator("data")
    @classmethod
    def unique_ids(cls, values: list[Model]) -> list[Model]:
        if len({m.id for m in values}) != len(values):
            raise ValueError("Duplicate WorkBuddy model IDs")
        return values
