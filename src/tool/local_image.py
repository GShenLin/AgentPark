"""Decode local images and prepare Codex-compatible image detail budgets."""

import base64
from io import BytesIO
import math
from pathlib import Path

from PIL import Image, ImageOps


_DETAIL_LIMITS = {"high": (2048, 2500), "original": (6000, 10000)}


def image_dimensions(width: int, height: int, detail: str) -> tuple[int, int]:
    max_dimension, max_patches = _DETAIL_LIMITS[detail]

    def fits(w: int, h: int) -> bool:
        return max(w, h) <= max_dimension and math.ceil(w / 32) * math.ceil(h / 32) <= max_patches

    if fits(width, height):
        return width, height
    scale = min(1.0, max_dimension / max(width, height))
    width, height = max(1, math.floor(width * scale + 0.5)), max(1, math.floor(height * scale + 0.5))
    if fits(width, height):
        return width, height
    scale = math.sqrt(32 * 32 * max_patches / width / height)
    wide, high = width * scale / 32, height * scale / 32
    scale *= min(math.floor(wide) / wide, math.floor(high) / high)
    return max(1, math.floor(width * scale)), max(1, math.floor(height * scale))


def prepare_local_image(path: str, detail: str = "high") -> dict:
    if detail not in _DETAIL_LIMITS:
        raise ValueError("view_image.detail must be 'high' or 'original'")
    source = Path(path)
    if not source.is_file():
        raise ValueError(f"Image path is not a file: {source}")
    raw = source.read_bytes()
    try:
        with Image.open(BytesIO(raw)) as decoded:
            decoded.load()
            original_format = decoded.format
            image = ImageOps.exif_transpose(decoded)
            source_size = image.size
            size = image_dimensions(*source_size, detail)
            preserve = size == source_size and original_format in {"PNG", "JPEG", "WEBP"} and decoded.getexif().get(274, 1) == 1
            if preserve:
                mime = Image.MIME[original_format]
            else:
                if size != source_size:
                    image = image.resize(size, Image.Resampling.BILINEAR)
                image = image.convert("RGBA" if "A" in image.getbands() or "transparency" in image.info else "RGB")
                buffer = BytesIO()
                image.save(buffer, format="PNG")
                raw, mime = buffer.getvalue(), "image/png"
    except (OSError, ValueError, Image.DecompressionBombError) as exc:
        raise ValueError(f"Unable to decode image {source}: {exc}") from exc
    return {
        "kind": "local_image", "status": "success", "image_path": str(source),
        "mime_type": mime, "detail": detail, "width": size[0], "height": size[1],
        "source_width": source_size[0], "source_height": source_size[1],
        "resized": size != source_size, "base64_image": base64.b64encode(raw).decode("ascii"),
    }
