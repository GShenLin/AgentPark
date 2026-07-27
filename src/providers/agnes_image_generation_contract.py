from __future__ import annotations


_RESPONSE_FORMATS = frozenset({"url", "b64_json"})


def build_agnes_image_payload(
    *,
    model: object,
    prompt: object,
    size: object,
    response_format: object = "url",
    image: object = None,
    **_unsupported_options: object,
) -> dict:
    """Build the Agnes Image 2.x ``/images/generations`` request body."""
    model_id = str(model or "").strip()
    prompt_text = str(prompt or "").strip()
    size_value = str(size or "").strip()
    response_value = str(response_format or "url").strip().lower()

    if not model_id:
        raise ValueError("model is required for Agnes image generation")
    if not prompt_text:
        raise ValueError("prompt is required for Agnes image generation")
    if not size_value:
        raise ValueError("size is required for Agnes image generation")
    if response_value not in _RESPONSE_FORMATS:
        raise ValueError("response_format must be 'url' or 'b64_json'")

    references = _normalize_references(image)
    extra_body: dict[str, object] = {"response_format": response_value}
    if references:
        extra_body["image"] = references

    return {
        "model": model_id,
        "prompt": prompt_text,
        "size": size_value,
        "extra_body": extra_body,
    }


def _normalize_references(image: object) -> list[str]:
    if image is None:
        return []
    values = image if isinstance(image, (list, tuple)) else (image,)
    return [str(item).strip() for item in values if str(item or "").strip()]
