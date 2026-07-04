import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.web_backend import pet_avatar as pet_avatar_module
from src.web_backend.pet_avatar import PetAvatarDomain


def _write_avatar_frame(root, avatar_id="demo", name="Demo"):
    avatar_dir = root / "petAvatars" / avatar_id
    avatar_dir.mkdir(parents=True)
    (avatar_dir / "frame.json").write_text(
        json.dumps(
            {
                "version": 1,
                "id": avatar_id,
                "name": name,
                "renderer": "sprite2d",
                "fps": 12,
                "states": {
                    "idle": {
                        "type": "sequence",
                        "loop": True,
                        "frames": [{"src": "idle/missing.png", "holdFrames": 4}],
                    }
                },
            }
        ),
        encoding="utf-8",
    )
    return avatar_dir


def test_list_pet_avatars_uses_deferred_asset_validation(monkeypatch, tmp_path):
    _write_avatar_frame(tmp_path)
    monkeypatch.setattr(pet_avatar_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = PetAvatarDomain(SimpleNamespace())

    result = domain.list_pet_avatars()

    assert result["avatars"] == [
        {
            "id": "demo",
            "name": "Demo",
            "renderer": "sprite2d",
            "fps": 12,
            "states": ["idle"],
            "path": str(tmp_path / "petAvatars" / "demo"),
            "valid": True,
            "asset_validation": "deferred",
        }
    ]


def test_get_pet_avatar_still_requires_referenced_assets(monkeypatch, tmp_path):
    _write_avatar_frame(tmp_path)
    monkeypatch.setattr(pet_avatar_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = PetAvatarDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc_info:
        domain.get_pet_avatar("demo")

    assert exc_info.value.status_code == 400
    assert "references missing asset" in exc_info.value.detail


def test_sequence_tracks_are_validated_and_sorted(monkeypatch, tmp_path):
    avatar_dir = tmp_path / "petAvatars" / "demo"
    (avatar_dir / "idle").mkdir(parents=True)
    (avatar_dir / "idle" / "frame.png").write_bytes(b"png")
    monkeypatch.setattr(pet_avatar_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = PetAvatarDomain(SimpleNamespace())

    result = domain.update_pet_avatar_frame(
        "demo",
        {
            "frame": {
                "version": 1,
                "id": "demo",
                "name": "Demo",
                "renderer": "sprite2d",
                "fps": 12,
                "states": {
                    "idle": {
                        "type": "sequence",
                        "loop": True,
                        "frames": [{"src": "idle/frame.png", "holdFrames": 10}],
                        "tracks": {
                            "transform": [
                                {"frame": 10, "x": 12, "y": -4, "rotation": 90, "scaleX": 1.5, "scaleY": 1.25},
                                {"frame": 0, "x": 0, "y": 0, "rotation": 0, "scaleX": 1, "scaleY": 1},
                            ],
                            "color": [
                                {"frame": 10, "color": "#FFAA00", "opacity": 0.25},
                                {"frame": 0, "color": "#ffffff", "opacity": 1},
                            ],
                        },
                    }
                },
            }
        },
    )

    tracks = result["avatar"]["states"]["idle"]["tracks"]
    assert [item["frame"] for item in tracks["transform"]] == [0, 10]
    assert tracks["color"][1] == {"frame": 10, "color": "#ffaa00", "opacity": 0.25}


def test_sequence_tracks_reject_duplicate_keyframes(monkeypatch, tmp_path):
    avatar_dir = tmp_path / "petAvatars" / "demo"
    (avatar_dir / "idle").mkdir(parents=True)
    (avatar_dir / "idle" / "frame.png").write_bytes(b"png")
    monkeypatch.setattr(pet_avatar_module, "_get_runtime_root", lambda: str(tmp_path))
    domain = PetAvatarDomain(SimpleNamespace())

    with pytest.raises(HTTPException) as exc_info:
        domain.update_pet_avatar_frame(
            "demo",
            {
                "frame": {
                    "version": 1,
                    "id": "demo",
                    "name": "Demo",
                    "renderer": "sprite2d",
                    "fps": 12,
                    "states": {
                        "idle": {
                            "type": "sequence",
                            "loop": True,
                            "frames": [{"src": "idle/frame.png", "holdFrames": 10}],
                            "tracks": {
                                "color": [
                                    {"frame": 4, "color": "#ffffff", "opacity": 1},
                                    {"frame": 4, "color": "#ff0000", "opacity": 0.5},
                                ]
                            },
                        }
                    },
                }
            },
        )

    assert exc_info.value.status_code == 400
    assert "duplicated" in exc_info.value.detail
