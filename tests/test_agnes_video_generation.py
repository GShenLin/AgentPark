import pytest

from src.providers.agnes_video_generation_contract import build_agnes_video_payload


def test_agnes_text_to_video_payload_matches_documented_contract():
    payload = build_agnes_video_payload(
        model="agnes-video-v2.0",
        content=[{"type": "text", "text": "A cinematic beach scene"}],
        resolution="720p",
        ratio="16:9",
        frames=121,
        seed=42,
    )
    assert payload == {
        "model": "agnes-video-v2.0",
        "prompt": "A cinematic beach scene",
        "width": 1152,
        "height": 768,
        "num_frames": 121,
        "frame_rate": 24,
        "seed": 42,
    }


def test_agnes_image_and_keyframe_inputs_use_distinct_contracts():
    one_image = build_agnes_video_payload(
        model="agnes-video-v2.0",
        content=[
            {"type": "text", "text": "Animate this"},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
        ],
        frames=81,
    )
    assert one_image["image"] == "https://example.com/a.png"
    assert "extra_body" not in one_image

    keyframes = build_agnes_video_payload(
        model="agnes-video-v2.0",
        content=[
            {"type": "text", "text": "Transition"},
            {"type": "image_url", "image_url": {"url": "https://example.com/a.png"}},
            {"type": "image_url", "image_url": {"url": "https://example.com/b.png"}},
        ],
        frames=81,
    )
    assert keyframes["extra_body"] == {
        "image": ["https://example.com/a.png", "https://example.com/b.png"],
        "mode": "keyframes",
    }


def test_agnes_video_frames_follow_8n_plus_1_rule():
    with pytest.raises(ValueError, match=r"8n \+ 1"):
        build_agnes_video_payload(
            model="agnes-video-v2.0",
            content=[{"type": "text", "text": "Animate"}],
            frames=120,
        )
