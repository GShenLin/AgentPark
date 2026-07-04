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


def test_normalize_avatar_style_accepts_empty_and_valid_avatar_id():
    domain = NodeDesktopViewDomain(SimpleNamespace(pet_avatars=FakePetAvatars({"test"})))

    assert domain._normalize_avatar_style("") == ""
    assert domain._normalize_avatar_style(" test ") == "test"


def test_normalize_avatar_style_rejects_non_string_and_unknown_avatar_id():
    domain = NodeDesktopViewDomain(SimpleNamespace(pet_avatars=FakePetAvatars({"test"})))

    with pytest.raises(HTTPException) as type_error:
        domain._normalize_avatar_style(123)
    assert type_error.value.status_code == 400
    assert type_error.value.detail == "avatar_style must be string"

    with pytest.raises(HTTPException) as missing_error:
        domain._normalize_avatar_style("missing")
    assert missing_error.value.status_code == 404
