from src.media_resource_utils import dedupe_preserve_order
from src.media_resource_utils import parse_resource_list
from src.media_resource_utils import uri_has_extension
from src.message_protocol import normalize_envelope


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}


def _is_image_uri(uri: object) -> bool:
    return uri_has_extension(uri, _IMAGE_EXTS)


def resolve_model_generation_inputs(
    message: object,
    *,
    prompt: object = "",
    images: object = "",
) -> tuple[str, list[str]]:
    envelope = normalize_envelope(message, default_role="user")
    parts = envelope.get("parts") if isinstance(envelope, dict) else []
    text_parts: list[str] = []
    image_uris = parse_resource_list(images)

    for part in parts if isinstance(parts, list) else []:
        if not isinstance(part, dict):
            continue
        part_type = str(part.get("type") or "").strip().lower()
        if part_type == "text":
            text = str(part.get("text") or "").strip()
            if text:
                text_parts.append(text)
            continue
        if part_type != "resource":
            continue
        resource = part.get("resource")
        if not isinstance(resource, dict):
            continue
        uri = str(resource.get("uri") or "").strip()
        kind = str(resource.get("kind") or "").strip().lower()
        if uri and (kind == "image" or (kind in {"file", "url", ""} and _is_image_uri(uri))):
            image_uris.append(uri)

    resolved_prompt = "\n".join(text_parts).strip() or str(prompt or "").strip()
    deduped_images = dedupe_preserve_order(image_uris)

    if not resolved_prompt and not deduped_images:
        raise ValueError("Model generation requires a prompt or at least one image.")
    if len(deduped_images) > 5:
        raise ValueError("Hyper3D Rodin supports at most 5 images.")
    return resolved_prompt, deduped_images
