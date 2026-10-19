from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Contract(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True, allow_inf_nan=False)


class Display(Contract):
    id: str = Field(min_length=1, max_length=100)
    label: str = Field(min_length=1, max_length=150)
    x: int
    y: int
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    primary: bool


class CaptureRequest(Contract):
    action: Literal['displays', 'frame']
    display_id: str = Field(default='', max_length=100)
    max_chars: int = Field(default=180000, ge=16000, le=500000)

    @model_validator(mode='after')
    def selection(self):
        if (self.action == 'frame') != bool(self.display_id):
            raise ValueError('Only frame requests require an explicit display_id.')
        return self


class DisplayCatalog(Contract):
    device_name: str = Field(min_length=1, max_length=150)
    displays: list[Display] = Field(min_length=1, max_length=32)


class CapturedFrame(Contract):
    display_id: str = Field(min_length=1, max_length=100)
    captured_at: str
    width: int = Field(gt=0, le=1600)
    height: int = Field(gt=0, le=1600)
    image: str = Field(pattern=r'^data:image/jpeg;base64,[A-Za-z0-9+/]+=*$', max_length=500000)
