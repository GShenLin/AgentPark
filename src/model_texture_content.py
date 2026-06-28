from src.media_resource_utils import parse_resource_list
from src.media_resource_utils import uri_has_extension
from src.message_protocol import normalize_envelope


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif", ".tif", ".tiff"}
_MODEL_EXTS = {".glb", ".gltf", ".obj", ".fbx", ".usdz", ".stl"}


def _looks_like_image(uri: object) -> bool:
    return uri_has_extension(uri, _IMAGE_EXTS)


def _looks_like_model(uri: object) -> bool:
    return uri_has_extension(uri, _MODEL_EXTS)


def resolve_model_texture_inputs(
    message: object,
    *,
    model_path: object = "",
    image_path: object = "",
    prompt: object = "",
) -> tuple[str, str, str]:
    envelope = normalize_envelope(message, default_role="user")
    parts = envelope.get("parts") if isinstance(envelope, dict) else []
    text_parts: list[str] = []
    model_candidates = parse_resource_list(model_path)
    image_candidates = parse_resource_list(image_path)

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
        if not uri:
            continue
        if kind == "image" or _looks_like_image(uri):
            image_candidates.append(uri)
            continue
        if kind in {"file", "url", "doc"} and _looks_like_model(uri):
            model_candidates.append(uri)

    model_uri = next((item for item in model_candidates if _looks_like_model(item)), "")
    image_uri = next((item for item in image_candidates if _looks_like_image(item)), "")
    resolved_prompt = "\n".join(text_parts).strip() or str(prompt or "").strip()

    if not model_uri:
        raise ValueError("Texture generation requires one model file path or URL.")
    if not image_uri:
        raise ValueError("Texture generation requires one reference image path or URL.")
    return model_uri, image_uri, resolved_prompt
