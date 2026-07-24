"""Video generation schema merged into the Agent node."""

GENERATION_CONFIG_DEFAULTS = {
    "video_resolution": "",
    "video_ratio": "",
    "video_duration": "",
    "video_frames": "",
    "video_seed": -1,
    "video_camera_fixed": False,
    "video_watermark": True,
    "video_generate_audio": True,
    "video_return_last_frame": False,
    "video_filename_prefix": "generated_video",
}

GENERATION_CONFIG_SCHEMA = {
    "video_resolution": {
        "type": "select",
        "label": "video_resolution",
        "options": [{"value": "", "label": "provider default"}, {"value": "480p", "label": "480p"}, {"value": "720p", "label": "720p"}],
    },
    "video_ratio": {
        "type": "select",
        "label": "video_ratio",
        "options": [{"value": "", "label": "provider default"}] + [
            {"value": value, "label": value}
            for value in ("16:9", "4:3", "1:1", "3:4", "9:16", "21:9", "adaptive")
        ],
    },
    "video_duration": {"type": "number", "label": "video_duration", "min": -1, "max": 15},
    "video_frames": {"type": "number", "label": "video_frames", "min": 1},
    "video_seed": {"type": "number", "label": "video_seed", "min": -1, "max": 4294967295},
    "video_camera_fixed": {"type": "boolean", "label": "video_camera_fixed"},
    "video_watermark": {"type": "boolean", "label": "video_watermark"},
    "video_generate_audio": {"type": "boolean", "label": "video_generate_audio"},
    "video_return_last_frame": {"type": "boolean", "label": "video_return_last_frame"},
    "video_filename_prefix": {"type": "string", "label": "video_filename_prefix"},
}
