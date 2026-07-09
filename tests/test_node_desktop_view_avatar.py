from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend.node_desktop_view import NodeDesktopViewDomain


class FakePetAvatars:
    def __init__(self, valid_ids: set[str]) -> None:
        self.valid_ids = valid_ids

    def get_pet_avatar(self, avatar_id: str):
        if avatar_id not in self.valid_ids:
            raise HTTPException(status_code=404, detail="avatar not found")
        return {"avatar": {"id": avatar_id}}


def test_validate_avatar_style_accepts_empty_and_valid_avatar_id():
    domain = NodeDesktopViewDomain(SimpleNamespace(pet_avatars=FakePetAvatars({"test"})))

    assert domain._validate_avatar_style("") == ""
    assert domain._validate_avatar_style(" test ") == "test"


def test_validate_avatar_style_rejects_non_string_and_unknown_avatar_id():
    domain = NodeDesktopViewDomain(SimpleNamespace(pet_avatars=FakePetAvatars({"test"})))

    with pytest.raises(HTTPException) as type_error:
        domain._validate_avatar_style(123)
    assert type_error.value.status_code == 400
    assert type_error.value.detail == "avatar_style must be string"

    with pytest.raises(HTTPException) as missing_error:
        domain._validate_avatar_style("missing")
    assert missing_error.value.status_code == 404


def test_validate_panel_size_accepts_supported_dimensions():
    domain = NodeDesktopViewDomain(SimpleNamespace())

    assert domain._validate_panel_size({"width": 320, "height": 360}) == {"width": 320, "height": 360}
    assert domain._validate_panel_size({"width": 1600, "height": 1200}) == {"width": 1600, "height": 1200}
    assert domain._validate_panel_size(None) is None


def test_validate_panel_size_rejects_invalid_payloads():
    domain = NodeDesktopViewDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as type_error:
        domain._validate_panel_size("320x360")
    assert type_error.value.status_code == 400
    assert type_error.value.detail == "panel_size must be an object"

    with pytest.raises(HTTPException) as range_error:
        domain._validate_panel_size({"width": 120, "height": 360})
    assert range_error.value.status_code == 400
    assert range_error.value.detail == "panel_size.width is below the supported minimum"

    with pytest.raises(HTTPException) as string_error:
        domain._validate_panel_size({"width": "320", "height": 360})
    assert string_error.value.status_code == 400
    assert string_error.value.detail == "panel_size.width and panel_size.height must be integers"
