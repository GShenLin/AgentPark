from __future__ import annotations

import math
import re
from typing import Any

from .shared import HTTPException


HEX_COLOR_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")


def validate_sequence_tracks(state_id: str, tracks: object, total_frames: int) -> dict[str, Any]:
    if tracks is None:
        return {}
    if not isinstance(tracks, dict):
        raise HTTPException(status_code=400, detail=f"state '{state_id}' tracks must be an object")
    unknown = set(tracks.keys()) - {"transform", "color"}
    if unknown:
        names = ", ".join(sorted(str(name) for name in unknown))
        raise HTTPException(status_code=400, detail=f"state '{state_id}' tracks contain unsupported keys: {names}")
    normalized: dict[str, Any] = {}
    if "transform" in tracks:
        transform = _validate_transform_track(state_id, tracks.get("transform"), total_frames)
        if transform:
            normalized["transform"] = transform
    if "color" in tracks:
        color = _validate_color_track(state_id, tracks.get("color"), total_frames)
        if color:
            normalized["color"] = color
    return normalized


def _validate_keyframe_frame(state_id: str, track_name: str, index: int, value: object, total_frames: int) -> int:
    if type(value) is not int or value < 0 or value > total_frames:
        raise HTTPException(
            status_code=400,
            detail=f"state '{state_id}' {track_name} keyframe {index} frame must be an integer between 0 and {total_frames}",
        )
    return value


def _validate_keyframe_number(
    state_id: str,
    track_name: str,
    index: int,
    field: str,
    value: object,
    *,
    minimum: float,
    maximum: float,
) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
        raise HTTPException(status_code=400, detail=f"state '{state_id}' {track_name} keyframe {index} {field} must be a number")
    number = float(value)
    if number < minimum or number > maximum:
        raise HTTPException(
            status_code=400,
            detail=f"state '{state_id}' {track_name} keyframe {index} {field} must be between {minimum:g} and {maximum:g}",
        )
    return number


def _validate_transform_track(state_id: str, track: object, total_frames: int) -> list[dict[str, Any]]:
    if not isinstance(track, list):
        raise HTTPException(status_code=400, detail=f"state '{state_id}' transform track must be a list")
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for index, keyframe in enumerate(track):
        if not isinstance(keyframe, dict):
            raise HTTPException(status_code=400, detail=f"state '{state_id}' transform keyframe {index} must be an object")
        frame = _validate_keyframe_frame(state_id, "transform", index, keyframe.get("frame"), total_frames)
        if frame in seen:
            raise HTTPException(status_code=400, detail=f"state '{state_id}' transform keyframe frame {frame} is duplicated")
        seen.add(frame)
        normalized.append(
            {
                "frame": frame,
                "x": _validate_keyframe_number(state_id, "transform", index, "x", keyframe.get("x"), minimum=-10000, maximum=10000),
                "y": _validate_keyframe_number(state_id, "transform", index, "y", keyframe.get("y"), minimum=-10000, maximum=10000),
                "rotation": _validate_keyframe_number(
                    state_id,
                    "transform",
                    index,
                    "rotation",
                    keyframe.get("rotation"),
                    minimum=-3600,
                    maximum=3600,
                ),
                "scaleX": _validate_keyframe_number(state_id, "transform", index, "scaleX", keyframe.get("scaleX"), minimum=0.01, maximum=20),
                "scaleY": _validate_keyframe_number(state_id, "transform", index, "scaleY", keyframe.get("scaleY"), minimum=0.01, maximum=20),
            }
        )
    return sorted(normalized, key=lambda item: item["frame"])


def _validate_color_track(state_id: str, track: object, total_frames: int) -> list[dict[str, Any]]:
    if not isinstance(track, list):
        raise HTTPException(status_code=400, detail=f"state '{state_id}' color track must be a list")
    seen: set[int] = set()
    normalized: list[dict[str, Any]] = []
    for index, keyframe in enumerate(track):
        if not isinstance(keyframe, dict):
            raise HTTPException(status_code=400, detail=f"state '{state_id}' color keyframe {index} must be an object")
        frame = _validate_keyframe_frame(state_id, "color", index, keyframe.get("frame"), total_frames)
        if frame in seen:
            raise HTTPException(status_code=400, detail=f"state '{state_id}' color keyframe frame {frame} is duplicated")
        seen.add(frame)
        color = str(keyframe.get("color") or "").strip()
        if not HEX_COLOR_RE.match(color):
            raise HTTPException(status_code=400, detail=f"state '{state_id}' color keyframe {index} color must be #RRGGBB")
        normalized.append(
            {
                "frame": frame,
                "color": color.lower(),
                "opacity": _validate_keyframe_number(state_id, "color", index, "opacity", keyframe.get("opacity"), minimum=0, maximum=1),
            }
        )
    return sorted(normalized, key=lambda item: item["frame"])
