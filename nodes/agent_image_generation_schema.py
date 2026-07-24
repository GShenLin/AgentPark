"""Schema contract for the Agent node's image_generation SupportMode."""

from __future__ import annotations

from src.providers.doubao_image_generation_contract import seedream_image_capabilities


IMAGE_CONFIG_DEFAULTS = {
    "image_references": [],
    "image_size": "2K",
    "image_aspect_ratio": "",
    "image_optimize_prompt_mode": "",
    "image_output_format": "",
    "image_response_format": "url",
    "image_sequential_image_generation": "disabled",
    "image_max_images": 15,
    "image_stream": False,
    "image_tools": [],
    "image_watermark": True,
    "image_filename_prefix": "generated_image",
}


IMAGE_CONFIG_SCHEMA = {
    "image_references": {
        "type": "file_list",
        "label": "image_references",
        "description": (
            "Optional project files selected from the file tree. "
            "Images attached to the input message are appended at request time."
        ),
    },
    "image_size": {
        "type": "image_dimensions",
        "label": "image_size",
        "options": [{"value": value, "label": value} for value in ("1K", "2K", "3K", "4K")],
        "aspect_ratios": [
            {"value": value, "label": value}
            for value in ("21:9", "16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16")
        ],
        "aspect_ratio_field": "image_aspect_ratio",
        "custom_dimensions_supported": True,
        "description": "Resolution tier or exact '<width>x<height>' pixels. Model-specific pixel and aspect-ratio limits apply.",
    },
    "image_aspect_ratio": {
        "type": "select",
        "label": "image_aspect_ratio",
        "hidden": True,
        "options": [{"value": "", "label": "provider default"}] + [
            {"value": value, "label": value}
            for value in ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
        ],
        "description": "Provider-specific aspect-ratio control. Seedream expresses shape or usage in the prompt instead.",
    },
    "image_optimize_prompt_mode": {
        "type": "select",
        "label": "optimize_prompt_options.mode",
        "options": [
            {"value": "", "label": "standard (provider default)"},
            {"value": "standard", "label": "standard"},
            {"value": "fast", "label": "fast"},
        ],
        "description": "Seedream prompt optimization mode. standard favors quality; fast favors latency.",
    },
    "image_output_format": {
        "type": "select",
        "label": "output_format",
        "options": [
            {"value": "", "label": "jpeg (provider default)"},
            {"value": "jpeg", "label": "jpeg"},
            {"value": "png", "label": "png"},
        ],
        "description": "Generated image file format. Documented for Seedream 5.0 pro and 5.0 lite.",
    },
    "image_response_format": {
        "type": "select",
        "label": "response_format",
        "options": [{"value": value, "label": value} for value in ("url", "b64_json")],
        "description": "url links expire after 24 hours; AgentPark downloads them immediately. b64_json returns image bytes inline.",
    },
    "image_sequential_image_generation": {
        "type": "select",
        "label": "sequential_image_generation",
        "options": [{"value": value, "label": value} for value in ("disabled", "auto")],
        "description": "auto allows the model to return a related image sequence; disabled returns one image.",
    },
    "image_max_images": {
        "type": "number",
        "label": "sequential_image_generation_options.max_images",
        "min": 1,
        "max": 15,
        "step": 1,
        "visible_when": {"field": "image_sequential_image_generation", "equals": "auto"},
        "description": "Maximum generated images. Reference image count plus generated image count cannot exceed 15.",
    },
    "image_stream": {
        "type": "boolean",
        "label": "stream",
        "description": "Return each generated image as it becomes available.",
    },
    "image_tools": {
        "type": "multiselect",
        "label": "tools",
        "options": [{"value": "web_search", "label": "web_search"}],
        "description": "Seedream image tools. web_search is documented for Seedream 5.0 lite.",
    },
    "image_watermark": {
        "type": "boolean",
        "label": "watermark",
        "description": "Add the provider's 'AI generated' watermark in the lower-right corner.",
    },
    "image_filename_prefix": {
        "type": "string",
        "label": "filename_prefix",
        "description": "Prefix used when AgentPark saves generated image files.",
    },
}


def materialize_image_generation_schema(schema: dict, provider_config: dict | None) -> dict:
    """Apply provider and documented Seedream model capabilities to the schema."""
    output = dict(schema)
    provider = provider_config if isinstance(provider_config, dict) else {}
    provider_type = str(provider.get("type") or "").strip().lower()
    image_fields = set(IMAGE_CONFIG_SCHEMA)

    if provider_type == "gemini":
        supported = {"image_references", "image_size", "image_aspect_ratio", "image_filename_prefix"}
        output = {key: value for key, value in output.items() if key not in image_fields or key in supported}
        size_schema = dict(output.get("image_size") or {})
        size_schema["options"] = [
            {"value": value, "label": value}
            for value in ("1K", "2K", "4K")
        ]
        size_schema["custom_dimensions_supported"] = False
        size_schema["description"] = (
            "Choose an output resolution and aspect ratio. Gemini imageSize accepts 1K, 2K or 4K; "
            "aspectRatio is sent separately."
        )
        output["image_size"] = size_schema
        return output
    if provider_type != "doubao":
        return output

    output.pop("image_aspect_ratio", None)
    capabilities = seedream_image_capabilities(provider.get("model"))
    if capabilities is None:
        return output

    size_schema = dict(output.get("image_size") or {})
    size_schema["type"] = "image_dimensions"
    size_schema["options"] = [
        {"value": value, "label": value}
        for value in capabilities.size_presets
    ]
    size_schema["aspect_ratios"] = [
        {"value": value, "label": value}
        for value in ("21:9", "16:9", "3:2", "4:3", "1:1", "3:4", "2:3", "9:16")
    ]
    size_schema["min_pixels"] = capabilities.min_pixels
    size_schema["max_pixels"] = capabilities.max_pixels
    size_schema["aspect_ratio_field"] = ""
    size_schema["custom_dimensions_supported"] = True
    size_schema["description"] = (
        f"{capabilities.family}: {', '.join(capabilities.size_presets)} or exact '<width>x<height>'; "
        f"{capabilities.min_pixels}..{capabilities.max_pixels} pixels and aspect ratio 1/16..16."
    )
    output["image_size"] = size_schema

    references_schema = dict(output.get("image_references") or {})
    references_schema["description"] = (
        f"Select optional input images from the project file tree. "
        f"{capabilities.family} accepts at most {capabilities.max_reference_images}."
    )
    output["image_references"] = references_schema

    optimize_schema = dict(output.get("image_optimize_prompt_mode") or {})
    optimize_schema["options"] = [
        {"value": "", "label": "standard (provider default)"},
        *[
            {"value": value, "label": value}
            for value in capabilities.prompt_optimization_modes
        ],
    ]
    output["image_optimize_prompt_mode"] = optimize_schema

    if not capabilities.supports_output_format:
        output.pop("image_output_format", None)
    if not capabilities.supports_sequential_images:
        output.pop("image_sequential_image_generation", None)
        output.pop("image_max_images", None)
    if not capabilities.supports_stream:
        output.pop("image_stream", None)
    if not capabilities.supports_web_search:
        output.pop("image_tools", None)
    return output
