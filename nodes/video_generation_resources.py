from src.media_resource_utils import parse_resource_list
from src.message_protocol import build_resource_part, normalize_envelope


def merge_configured_video_resources(
    message: object,
    *,
    first_frame_path: object = "",
    last_frame_path: object = "",
    reference_images: object = "",
    reference_videos: object = "",
    reference_audios: object = "",
) -> dict:
    envelope = normalize_envelope(message, default_role="user")
    parts = list(envelope.get("parts") or [])

    _append_resource(parts, first_frame_path, kind="image", role="first_frame")
    _append_resource(parts, last_frame_path, kind="image", role="last_frame")

    for uri in parse_resource_list(reference_images):
        _append_resource(parts, uri, kind="image", role="reference_image")

    for uri in parse_resource_list(reference_videos):
        _append_resource(parts, uri, kind="video", role="reference_video")

    for uri in parse_resource_list(reference_audios):
        _append_resource(parts, uri, kind="audio", role="reference_audio")

    return normalize_envelope({"role": envelope.get("role") or "user", "parts": parts}, default_role="user")


def _append_resource(parts: list, value: object, kind: str, role: str) -> None:
    uri = str(value or "").strip()
    if not uri:
        return
    parts.append(
        build_resource_part(
            uri=uri,
            kind=kind,
            source="video_generation_node",
            metadata={"role": role},
        )
    )
