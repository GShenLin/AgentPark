from __future__ import annotations

from src.value_parsing import parse_optional_int_value


_DIMENSIONS = {
    ("480p", "16:9"): (832, 448),
    ("480p", "9:16"): (448, 832),
    ("480p", "1:1"): (640, 640),
    ("480p", "4:3"): (640, 480),
    ("480p", "3:4"): (480, 640),
    ("720p", "16:9"): (1152, 768),
    ("720p", "9:16"): (768, 1152),
    ("720p", "1:1"): (1024, 1024),
    ("720p", "4:3"): (1024, 768),
    ("720p", "3:4"): (768, 1024),
    ("1080p", "16:9"): (1920, 1080),
    ("1080p", "9:16"): (1080, 1920),
    ("1080p", "1:1"): (1536, 1536),
    ("1080p", "4:3"): (1440, 1080),
    ("1080p", "3:4"): (1080, 1440),
}


def build_agnes_video_payload(
    *,
    model: object,
    content: object,
    resolution: object = None,
    ratio: object = None,
    duration: object = None,
    frames: object = None,
    seed: object = None,
    frame_rate: object = 24,
    negative_prompt: object = None,
) -> dict:
    model_id = str(model or "").strip()
    prompt, images = _extract_content(content)
    if not model_id:
        raise ValueError("model is required for Agnes video generation")
    if not prompt:
        raise ValueError("prompt is required for Agnes video generation")

    fps = parse_optional_int_value("frame_rate", frame_rate, minimum=1, maximum=60) or 24
    num_frames = _resolve_num_frames(frames=frames, duration=duration, frame_rate=fps)
    width, height = _resolve_dimensions(resolution, ratio)

    payload: dict[str, object] = {
        "model": model_id,
        "prompt": prompt,
        "width": width,
        "height": height,
        "num_frames": num_frames,
        "frame_rate": fps,
    }
    if len(images) == 1:
        payload["image"] = images[0]
    elif images:
        payload["extra_body"] = {"image": images, "mode": "keyframes"}

    resolved_seed = parse_optional_int_value("seed", seed, allowed_values=(-1,), minimum=0)
    if resolved_seed is not None and resolved_seed != -1:
        payload["seed"] = resolved_seed
    negative = str(negative_prompt or "").strip()
    if negative:
        payload["negative_prompt"] = negative
    return payload


def _extract_content(content: object) -> tuple[str, list[str]]:
    if not isinstance(content, list):
        raise ValueError("Video generation content must be a list")
    text_parts: list[str] = []
    images: list[str] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type == "text":
            text = str(item.get("text") or "").strip()
            if text:
                text_parts.append(text)
        elif item_type == "image_url":
            image_value = item.get("image_url")
            url = (
                str(image_value.get("url") or "").strip()
                if isinstance(image_value, dict)
                else str(image_value or "").strip()
            )
            if url:
                images.append(url)
        elif item_type in {"video_url", "audio_url"}:
            raise ValueError(f"Agnes video generation does not support {item_type} input")
    return "\n".join(text_parts).strip(), images


def _resolve_num_frames(*, frames: object, duration: object, frame_rate: int) -> int:
    value = parse_optional_int_value("num_frames", frames, minimum=1, maximum=441)
    if value is None:
        seconds = parse_optional_int_value("duration", duration, allowed_values=(-1,), minimum=1)
        desired = 121 if seconds in (None, -1) else min(441, seconds * frame_rate)
        value = ((desired - 1) // 8) * 8 + 1
    if value > 441 or (value - 1) % 8 != 0:
        raise ValueError("num_frames must be <= 441 and follow the 8n + 1 rule")
    return value


def _resolve_dimensions(resolution: object, ratio: object) -> tuple[int, int]:
    resolution_value = str(resolution or "720p").strip().lower()
    ratio_value = str(ratio or "16:9").strip().lower()
    if ratio_value == "adaptive":
        ratio_value = "16:9"
    dimensions = _DIMENSIONS.get((resolution_value, ratio_value))
    if dimensions is None:
        raise ValueError(
            f"Unsupported Agnes video resolution/ratio: {resolution_value}/{ratio_value}"
        )
    return dimensions
