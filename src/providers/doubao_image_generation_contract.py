"""Typed request contract for Volcengine Ark Seedream image generation."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_CUSTOM_SIZE_PATTERN = re.compile(r"^(?P<width>[1-9]\d*)[xX](?P<height>[1-9]\d*)$")
_RESPONSE_FORMATS = frozenset({"url", "b64_json"})
_OUTPUT_FORMATS = frozenset({"jpeg", "png"})
_PROMPT_OPTIMIZATION_MODES = frozenset({"standard", "fast"})
_SEQUENTIAL_MODES = frozenset({"disabled", "auto"})
_IMAGE_TOOLS = frozenset({"web_search"})


@dataclass(frozen=True)
class SeedreamImageCapabilities:
    family: str
    size_presets: tuple[str, ...]
    default_size: str
    min_pixels: int
    max_pixels: int
    max_reference_images: int
    prompt_optimization_modes: tuple[str, ...]
    supports_output_format: bool
    supports_sequential_images: bool
    supports_stream: bool
    supports_web_search: bool


_SEEDREAM_5_LITE_CAPABILITIES = SeedreamImageCapabilities(
    family="seedream-5.0-lite",
    size_presets=("2K", "3K", "4K"),
    default_size="2048x2048",
    min_pixels=3_686_400,
    max_pixels=16_777_216,
    max_reference_images=14,
    prompt_optimization_modes=("standard",),
    supports_output_format=True,
    supports_sequential_images=True,
    supports_stream=True,
    supports_web_search=True,
)


_MODEL_CAPABILITIES = (
    (
        "doubao-seedream-5-0-pro",
        SeedreamImageCapabilities(
            family="seedream-5.0-pro",
            size_presets=("1K", "2K"),
            default_size="2K",
            min_pixels=921_600,
            max_pixels=4_624_220,
            max_reference_images=10,
            prompt_optimization_modes=("standard", "fast"),
            supports_output_format=True,
            supports_sequential_images=False,
            supports_stream=False,
            supports_web_search=False,
        ),
    ),
    (
        "doubao-seedream-5-0-260128",
        _SEEDREAM_5_LITE_CAPABILITIES,
    ),
    (
        "doubao-seedream-5-0-lite",
        _SEEDREAM_5_LITE_CAPABILITIES,
    ),
    (
        "doubao-seedream-4-5",
        SeedreamImageCapabilities(
            family="seedream-4.5",
            size_presets=("2K", "4K"),
            default_size="2048x2048",
            min_pixels=3_686_400,
            max_pixels=16_777_216,
            max_reference_images=14,
            prompt_optimization_modes=("standard",),
            supports_output_format=False,
            supports_sequential_images=True,
            supports_stream=True,
            supports_web_search=False,
        ),
    ),
    (
        "doubao-seedream-4-0",
        SeedreamImageCapabilities(
            family="seedream-4.0",
            size_presets=("1K", "2K", "4K"),
            default_size="2048x2048",
            min_pixels=921_600,
            max_pixels=16_777_216,
            max_reference_images=14,
            prompt_optimization_modes=("standard",),
            supports_output_format=False,
            supports_sequential_images=True,
            supports_stream=True,
            supports_web_search=False,
        ),
    ),
)


def seedream_image_capabilities(model: object) -> SeedreamImageCapabilities | None:
    """Resolve the documented contract for an official Seedream model ID."""
    normalized = str(model or "").strip().lower()
    for model_prefix, capabilities in _MODEL_CAPABILITIES:
        if normalized == model_prefix or normalized.startswith(f"{model_prefix}-"):
            return capabilities
    return None


def normalize_seedream_size(size: object, capabilities: SeedreamImageCapabilities | None) -> str:
    normalized = str(size or "").strip()
    if not normalized:
        return capabilities.default_size if capabilities else "2K"
    upper = normalized.upper()
    if upper in {"1K", "2K", "3K", "4K"}:
        if capabilities and upper not in capabilities.size_presets:
            allowed = ", ".join(capabilities.size_presets)
            raise ValueError(f"size '{upper}' is not supported by {capabilities.family}; expected one of: {allowed}")
        return upper

    match = _CUSTOM_SIZE_PATTERN.fullmatch(normalized)
    if not match:
        raise ValueError("size must be a supported resolution tier or '<width>x<height>' pixel dimensions")
    width = int(match.group("width"))
    height = int(match.group("height"))
    if capabilities:
        pixels = width * height
        ratio = width / height
        if pixels < capabilities.min_pixels or pixels > capabilities.max_pixels:
            raise ValueError(
                f"size {width}x{height} has {pixels} pixels; {capabilities.family} requires "
                f"{capabilities.min_pixels}..{capabilities.max_pixels}"
            )
        if ratio < 1 / 16 or ratio > 16:
            raise ValueError(f"size {width}x{height} has aspect ratio {ratio:g}; expected 1/16..16")
    return f"{width}x{height}"


def build_seedream_image_payload(
    *,
    model: object,
    prompt: object,
    size: object = None,
    response_format: object = "url",
    watermark: object = True,
    image: object = None,
    optimize_prompt_mode: object = None,
    output_format: object = None,
    sequential_image_generation: object = None,
    max_images: object = None,
    stream: object = False,
    tools: object = None,
) -> dict:
    """Build and validate the documented ``/images/generations`` body."""
    model_id = str(model or "").strip()
    prompt_text = str(prompt or "").strip()
    if not model_id:
        raise ValueError("model is required for image generation")
    if not prompt_text:
        raise ValueError("prompt is required for image generation")

    capabilities = seedream_image_capabilities(model_id)
    response_value = str(response_format or "url").strip().lower()
    if response_value not in _RESPONSE_FORMATS:
        raise ValueError("response_format must be 'url' or 'b64_json'")

    payload = {
        "model": model_id,
        "prompt": prompt_text,
        "size": normalize_seedream_size(size, capabilities),
        "response_format": response_value,
        "watermark": bool(watermark),
    }

    references = _normalize_references(image)
    if capabilities and len(references) > capabilities.max_reference_images:
        raise ValueError(
            f"{capabilities.family} accepts at most {capabilities.max_reference_images} reference images"
        )
    if references:
        payload["image"] = references[0] if len(references) == 1 else references

    optimization_mode = str(optimize_prompt_mode or "").strip().lower()
    if optimization_mode:
        if optimization_mode not in _PROMPT_OPTIMIZATION_MODES:
            raise ValueError("optimize_prompt_options.mode must be 'standard' or 'fast'")
        if capabilities and optimization_mode not in capabilities.prompt_optimization_modes:
            allowed = ", ".join(capabilities.prompt_optimization_modes)
            raise ValueError(
                f"optimize_prompt_options.mode '{optimization_mode}' is not supported by "
                f"{capabilities.family}; expected: {allowed}"
            )
        payload["optimize_prompt_options"] = {"mode": optimization_mode}

    output_value = str(output_format or "").strip().lower()
    if output_value:
        if output_value not in _OUTPUT_FORMATS:
            raise ValueError("output_format must be 'jpeg' or 'png'")
        if capabilities and not capabilities.supports_output_format:
            raise ValueError(f"output_format is not supported by {capabilities.family}")
        payload["output_format"] = output_value

    sequential_mode = str(sequential_image_generation or "disabled").strip().lower()
    if sequential_mode not in _SEQUENTIAL_MODES:
        raise ValueError("sequential_image_generation must be 'disabled' or 'auto'")
    if capabilities and not capabilities.supports_sequential_images:
        if sequential_mode == "auto":
            raise ValueError(f"sequential image generation is not supported by {capabilities.family}")
    else:
        payload["sequential_image_generation"] = sequential_mode
        if sequential_mode == "auto":
            max_value = 15 if max_images in (None, "") else _parse_max_images(max_images)
            payload["sequential_image_generation_options"] = {"max_images": max_value}

    stream_enabled = bool(stream)
    if stream_enabled and capabilities and not capabilities.supports_stream:
        raise ValueError(f"stream output is not supported by {capabilities.family}")
    if not capabilities or capabilities.supports_stream:
        payload["stream"] = stream_enabled

    tool_names = _normalize_tools(tools)
    if tool_names:
        if capabilities and not capabilities.supports_web_search:
            raise ValueError(f"image tools are not supported by {capabilities.family}")
        payload["tools"] = [{"type": name} for name in tool_names]
    return payload


def _normalize_references(image: object) -> list[str]:
    if image is None:
        return []
    values: Iterable[object] = image if isinstance(image, (list, tuple)) else (image,)
    return [str(item).strip() for item in values if str(item or "").strip()]


def _normalize_tools(tools: object) -> list[str]:
    if tools is None:
        return []
    values: Iterable[object] = tools if isinstance(tools, (list, tuple)) else (tools,)
    normalized: list[str] = []
    for item in values:
        value = str(item or "").strip().lower()
        if not value:
            continue
        if value not in _IMAGE_TOOLS:
            raise ValueError(f"unsupported image tool: {value}")
        if value not in normalized:
            normalized.append(value)
    return normalized


def _parse_max_images(value: object) -> int:
    if isinstance(value, bool):
        raise ValueError("max_images must be an integer from 1 to 15")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("max_images must be an integer from 1 to 15") from exc
    if parsed < 1 or parsed > 15:
        raise ValueError("max_images must be an integer from 1 to 15")
    return parsed
