"""Strict local validation for documented image-generation reference inputs."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO

from PIL import Image, UnidentifiedImageError


MAX_REFERENCE_IMAGE_BYTES = 30 * 1024 * 1024
MAX_REFERENCE_IMAGE_PIXELS = 36_000_000
MIN_REFERENCE_IMAGE_EDGE_EXCLUSIVE = 14

_FORMAT_MIME_TYPES = {
    "BMP": "image/bmp",
    "GIF": "image/gif",
    "HEIF": "image/heif",
    "JPEG": "image/jpeg",
    "PNG": "image/png",
    "TIFF": "image/tiff",
    "WEBP": "image/webp",
}
_HEIF_MIME_TYPES = frozenset({"image/heic", "image/heif"})


@dataclass(frozen=True)
class ReferenceImageInfo:
    mime_type: str
    width: int
    height: int
    byte_count: int


def validate_reference_dimensions(width: object, height: object) -> tuple[int, int]:
    try:
        parsed_width = int(width)
        parsed_height = int(height)
    except (TypeError, ValueError) as exc:
        raise ValueError("Reference image dimensions must be integers") from exc
    if parsed_width <= MIN_REFERENCE_IMAGE_EDGE_EXCLUSIVE or parsed_height <= MIN_REFERENCE_IMAGE_EDGE_EXCLUSIVE:
        raise ValueError("Reference image width and height must both be greater than 14 pixels")
    ratio = parsed_width / parsed_height
    if ratio < 1 / 16 or ratio > 16:
        raise ValueError(
            f"Reference image aspect ratio {ratio:g} is outside the documented range 1/16..16"
        )
    pixels = parsed_width * parsed_height
    if pixels > MAX_REFERENCE_IMAGE_PIXELS:
        raise ValueError(
            f"Reference image has {pixels} pixels; the documented maximum is {MAX_REFERENCE_IMAGE_PIXELS}"
        )
    return parsed_width, parsed_height


def validate_reference_image_bytes(
    content: bytes,
    *,
    declared_mime_type: str = "",
    source: str = "reference image",
) -> ReferenceImageInfo:
    if not isinstance(content, bytes) or not content:
        raise ValueError(f"{source} is empty")
    if len(content) > MAX_REFERENCE_IMAGE_BYTES:
        raise ValueError(f"{source} exceeds the documented 30MB limit")

    _register_heif_decoder()
    try:
        with Image.open(BytesIO(content)) as image:
            detected_format = str(image.format or "").strip().upper()
            width, height = validate_reference_dimensions(*image.size)
            image.verify()
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(f"{source} is not a decodable supported image") from exc

    detected_mime_type = _FORMAT_MIME_TYPES.get(detected_format)
    if not detected_mime_type:
        raise ValueError(f"{source} uses unsupported image format '{detected_format or 'unknown'}'")
    declared = str(declared_mime_type or "").strip().lower()
    if declared:
        compatible = (
            declared in _HEIF_MIME_TYPES and detected_format == "HEIF"
        ) or declared == detected_mime_type
        if not compatible:
            raise ValueError(
                f"{source} declares {declared} but contains {detected_mime_type} data"
            )
        normalized_mime_type = declared
    else:
        normalized_mime_type = detected_mime_type
    return ReferenceImageInfo(
        mime_type=normalized_mime_type,
        width=width,
        height=height,
        byte_count=len(content),
    )


def _register_heif_decoder() -> None:
    try:
        from pillow_heif import register_heif_opener
    except ImportError:
        return
    register_heif_opener()
