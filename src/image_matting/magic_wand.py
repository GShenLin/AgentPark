from __future__ import annotations

import os
import re
import uuid
from dataclasses import dataclass

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageOps, UnidentifiedImageError


_HEX_COLOR_PATTERN = re.compile(r"^#[0-9a-fA-F]{6}$")


@dataclass(frozen=True)
class MagicWandMattingConfig:
    tolerance: int = 1
    edge_softness: int = 0
    feather_px: float = 0.0
    background_color: str = ""

    @classmethod
    def from_values(
        cls,
        *,
        tolerance: object,
        edge_softness: object,
        feather_px: object,
        background_color: object,
    ) -> "MagicWandMattingConfig":
        return cls(
            tolerance=_parse_tolerance(tolerance),
            edge_softness=_parse_edge_softness(edge_softness),
            feather_px=_parse_feather(feather_px),
            background_color=_parse_background_color(background_color),
        )


def remove_connected_background(
    *,
    image_path: str,
    output_dir: str,
    filename_prefix: str,
    config: MagicWandMattingConfig,
) -> dict:
    source_path = os.path.abspath(str(image_path or "").strip())
    if not os.path.isfile(source_path):
        raise ValueError(f"Input image does not exist: {source_path or '<empty>'}")

    source = _load_image(source_path)
    rgb = source.convert("RGB")
    background_palette = (
        (_hex_to_rgb(config.background_color),)
        if config.background_color
        else _corner_background_palette(rgb)
    )
    candidate_mask = _build_background_candidate_mask(
        rgb,
        background_palette=background_palette,
        tolerance=config.tolerance,
    )
    background_mask = _select_border_connected(candidate_mask)
    background_pixels = background_mask.histogram()[255]
    total_pixels = rgb.width * rgb.height
    foreground_pixels = total_pixels - background_pixels

    alpha, clean_rgb, soft_edge_pixels = _reconstruct_soft_edge(
        rgb,
        background_palette=background_palette,
        background_mask=background_mask,
        tolerance=config.tolerance,
        edge_softness=config.edge_softness,
    )
    if config.feather_px > 0:
        blurred_alpha = alpha.filter(
            ImageFilter.GaussianBlur(radius=config.feather_px)
        )
        alpha = ImageChops.darker(alpha, blurred_alpha)
    if "A" in source.getbands():
        alpha = ImageChops.darker(alpha, source.getchannel("A"))
    alpha_min, alpha_max = alpha.getextrema()

    rgba = clean_rgb.convert("RGBA")
    rgba.putalpha(alpha)
    output_path = _save_png(rgba, output_dir=output_dir, filename_prefix=filename_prefix)
    return {
        "image_path": output_path,
        "status": "success",
        "method": "magic_wand",
        "background_mode": "explicit" if config.background_color else "corners",
        "background_color": (
            _rgb_to_hex(background_palette[0])
            if len(background_palette) == 1
            else ""
        ),
        "background_colors": [_rgb_to_hex(color) for color in background_palette],
        "tolerance": config.tolerance,
        "edge_softness": config.edge_softness,
        "feather_px": config.feather_px,
        "soft_edge_pixels": soft_edge_pixels,
        "width": rgba.width,
        "height": rgba.height,
        "alpha_min": int(alpha_min),
        "alpha_max": int(alpha_max),
        "background_pixels": int(background_pixels),
        "foreground_pixels": int(foreground_pixels),
    }


def _load_image(path: str) -> Image.Image:
    try:
        with Image.open(path) as opened:
            normalized = ImageOps.exif_transpose(opened)
            normalized.load()
            if normalized.width < 1 or normalized.height < 1:
                raise ValueError("Input image dimensions must be positive.")
            return normalized.copy()
    except ValueError:
        raise
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError(f"Input image is not decodable: {path}") from exc


def _corner_background_palette(
    image: Image.Image,
) -> tuple[tuple[int, int, int], ...]:
    width, height = image.size
    corners = (
        image.getpixel((0, 0)),
        image.getpixel((width - 1, 0)),
        image.getpixel((0, height - 1)),
        image.getpixel((width - 1, height - 1)),
    )
    return tuple(dict.fromkeys(corners))


def _build_background_candidate_mask(
    image: Image.Image,
    *,
    background_palette: tuple[tuple[int, int, int], ...],
    tolerance: int,
) -> Image.Image:
    candidate_mask = Image.new("L", image.size, 0)
    lookup = [255 if value <= tolerance else 0 for value in range(256)]
    for background_rgb in background_palette:
        reference = Image.new("RGB", image.size, background_rgb)
        difference = ImageChops.difference(image, reference)
        red, green, blue = difference.split()
        maximum_difference = ImageChops.lighter(
            ImageChops.lighter(red, green),
            blue,
        )
        color_mask = maximum_difference.point(lookup)
        candidate_mask = ImageChops.lighter(candidate_mask, color_mask)
    return candidate_mask


def _select_border_connected(candidate_mask: Image.Image) -> Image.Image:
    width, height = candidate_mask.size
    padded = Image.new("L", (width + 2, height + 2), 255)
    padded.paste(candidate_mask, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    connected = padded.crop((1, 1, width + 1, height + 1))
    return connected.point([255 if value == 128 else 0 for value in range(256)])


def _reconstruct_soft_edge(
    image: Image.Image,
    *,
    background_palette: tuple[tuple[int, int, int], ...],
    background_mask: Image.Image,
    tolerance: int,
    edge_softness: int,
) -> tuple[Image.Image, Image.Image, int]:
    alpha = ImageChops.invert(background_mask)
    clean_rgb = Image.composite(
        Image.new("RGB", image.size, (0, 0, 0)),
        image,
        background_mask,
    )
    if edge_softness == 0:
        return alpha, clean_rgb, 0

    soft_limit = min(255, tolerance + edge_softness)
    soft_candidate_mask = _build_background_candidate_mask(
        image,
        background_palette=background_palette,
        tolerance=soft_limit,
    )
    soft_connected_mask = _select_border_connected(soft_candidate_mask)
    soft_edge_mask = ImageChops.subtract(soft_connected_mask, background_mask)
    soft_edge_bounds = soft_edge_mask.getbbox()
    if soft_edge_bounds is None:
        return alpha, clean_rgb, 0

    source_pixels = image.load()
    output_pixels = clean_rgb.load()
    alpha_pixels = alpha.load()
    edge_pixels = soft_edge_mask.load()
    left, top, right, bottom = soft_edge_bounds
    soft_edge_pixels = 0
    for y in range(top, bottom):
        for x in range(left, right):
            if edge_pixels[x, y] == 0:
                continue
            source_rgb = source_pixels[x, y]
            background_rgb, edge_alpha = _closest_color_to_alpha(
                source_rgb,
                background_palette,
            )
            alpha_pixels[x, y] = edge_alpha
            output_pixels[x, y] = _remove_background_color(
                source_rgb,
                background_rgb,
                edge_alpha,
            )
            soft_edge_pixels += 1
    return alpha, clean_rgb, soft_edge_pixels


def _closest_color_to_alpha(
    color: tuple[int, int, int],
    background_palette: tuple[tuple[int, int, int], ...],
) -> tuple[tuple[int, int, int], int]:
    candidates = (
        (_color_to_alpha_value(color, background), background)
        for background in background_palette
    )
    alpha, background = min(candidates, key=lambda item: item[0])
    return background, alpha


def _color_to_alpha_value(
    color: tuple[int, int, int],
    background: tuple[int, int, int],
) -> int:
    required_alpha = 0.0
    for channel, background_channel in zip(color, background):
        if channel < background_channel and background_channel > 0:
            channel_alpha = (background_channel - channel) / background_channel
        elif channel > background_channel and background_channel < 255:
            channel_alpha = (channel - background_channel) / (
                255 - background_channel
            )
        else:
            channel_alpha = 0.0
        required_alpha = max(required_alpha, channel_alpha)
    return max(0, min(255, round(required_alpha * 255)))


def _remove_background_color(
    color: tuple[int, int, int],
    background: tuple[int, int, int],
    alpha: int,
) -> tuple[int, int, int]:
    if alpha <= 0:
        return (0, 0, 0)
    return tuple(
        max(
            0,
            min(
                255,
                round(
                    (
                        255 * channel
                        - (255 - alpha) * background_channel
                    )
                    / alpha
                ),
            ),
        )
        for channel, background_channel in zip(color, background)
    )


def _save_png(image: Image.Image, *, output_dir: str, filename_prefix: str) -> str:
    raw_output_dir = str(output_dir or "").strip()
    if not raw_output_dir:
        raise ValueError("output_dir is required.")
    prefix = re.sub(r"[^a-zA-Z0-9_-]", "_", str(filename_prefix or "").strip())
    if not prefix:
        raise ValueError("filename_prefix must contain a filename-safe character.")

    resolved_dir = os.path.abspath(raw_output_dir)
    os.makedirs(resolved_dir, exist_ok=True)
    destination = os.path.join(resolved_dir, f"{prefix}_{uuid.uuid4().hex}.png")
    temporary = f"{destination}.tmp"
    try:
        with open(temporary, "wb") as file_obj:
            image.save(file_obj, format="PNG", optimize=False)
        os.replace(temporary, destination)
    except OSError as exc:
        try:
            if os.path.exists(temporary):
                os.remove(temporary)
        except OSError:
            pass
        raise RuntimeError(f"Failed to save Magic Wand Alpha output: {exc}") from exc
    return destination


def _parse_tolerance(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("tolerance must be an integer from 0 to 255.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("tolerance must be an integer from 0 to 255.") from exc
    if str(value).strip() not in {str(parsed), f"{parsed}.0"} and not isinstance(value, int):
        raise ValueError("tolerance must be an integer from 0 to 255.")
    if parsed < 0 or parsed > 255:
        raise ValueError("tolerance must be an integer from 0 to 255.")
    return parsed


def _parse_edge_softness(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("edge_softness must be an integer from 0 to 255.")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "edge_softness must be an integer from 0 to 255."
        ) from exc
    if str(value).strip() not in {str(parsed), f"{parsed}.0"} and not isinstance(
        value,
        int,
    ):
        raise ValueError("edge_softness must be an integer from 0 to 255.")
    if parsed < 0 or parsed > 255:
        raise ValueError("edge_softness must be an integer from 0 to 255.")
    return parsed


def _parse_feather(value: object) -> float:
    if isinstance(value, bool):
        raise ValueError("feather_px must be a number from 0 to 32.")
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("feather_px must be a number from 0 to 32.") from exc
    if not 0 <= parsed <= 32:
        raise ValueError("feather_px must be a number from 0 to 32.")
    return parsed


def _parse_background_color(value: object) -> str:
    text = str(value or "").strip()
    if text and not _HEX_COLOR_PATTERN.fullmatch(text):
        raise ValueError("background_color must be blank or use #RRGGBB format.")
    return text.upper()


def _hex_to_rgb(value: str) -> tuple[int, int, int]:
    return tuple(int(value[index : index + 2], 16) for index in (1, 3, 5))


def _rgb_to_hex(value: tuple[int, int, int]) -> str:
    return f"#{value[0]:02X}{value[1]:02X}{value[2]:02X}"
