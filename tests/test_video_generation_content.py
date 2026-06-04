def test_build_doubao_video_generation_content_accepts_local_image_as_base64(tmp_path):
    from src.video_generation_content import build_doubao_video_generation_content

    image_path = tmp_path / "demo.png"
    image_path.write_bytes(b"png")
    message = {
        "role": "user",
        "parts": [
            {"type": "text", "text": "生成视频"},
            {
                "type": "resource",
                "resource": {
                    "kind": "image",
                    "uri": str(image_path),
                    "metadata": {"role": "first_frame"},
                },
            },
        ],
    }

    content = build_doubao_video_generation_content(message)

    assert content[0] == {"type": "text", "text": "生成视频"}
    assert content[1]["type"] == "image_url"
    assert content[1]["role"] == "first_frame"
    assert content[1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_build_doubao_video_generation_content_accepts_local_audio_as_base64(tmp_path):
    from src.video_generation_content import build_doubao_video_generation_content

    audio_path = tmp_path / "track.mp3"
    audio_path.write_bytes(b"mp3")
    message = {
        "role": "user",
        "parts": [
            {"type": "resource", "resource": {"kind": "audio", "uri": str(audio_path)}},
        ],
    }

    content = build_doubao_video_generation_content(
        message,
        fallback_prompt="补充提示词",
    )

    assert content[0] == {"type": "text", "text": "补充提示词"}
    assert content[1]["type"] == "audio_url"
    assert content[1]["role"] == "reference_audio"
    assert content[1]["audio_url"]["url"].startswith("data:audio/mpeg;base64,")


def test_build_doubao_video_generation_content_rejects_local_video_without_public_base_url(tmp_path):
    from src.video_generation_content import build_doubao_video_generation_content

    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"mp4")
    message = {
        "role": "user",
        "parts": [
            {"type": "resource", "resource": {"kind": "video", "uri": str(video_path)}},
        ],
    }

    try:
        build_doubao_video_generation_content(message)
        assert False, "expected error"
    except ValueError as exc:
        assert "Local video paths require asset://" in str(exc)


def test_build_doubao_video_generation_content_exposes_local_video_via_public_base_url(tmp_path):
    from src.video_generation_content import build_doubao_video_generation_content

    video_path = tmp_path / "demo.mp4"
    video_path.write_bytes(b"mp4")
    message = {
        "role": "user",
        "parts": [
            {"type": "resource", "resource": {"kind": "video", "uri": str(video_path)}},
        ],
    }

    content = build_doubao_video_generation_content(
        message,
        public_base_url="https://public.example.com",
        fallback_prompt="补充提示词",
    )

    assert content[0] == {"type": "text", "text": "补充提示词"}
    assert content[1]["type"] == "video_url"
    assert content[1]["role"] == "reference_video"
    assert content[1]["video_url"]["url"].startswith("https://public.example.com/api/files/raw?path=")


def test_build_doubao_video_generation_content_infers_kind_from_file_extension(tmp_path):
    from src.video_generation_content import build_doubao_video_generation_content

    image_path = tmp_path / "frame.jpg"
    image_path.write_bytes(b"jpg")
    message = {
        "role": "user",
        "parts": [
            {"type": "resource", "resource": {"kind": "file", "uri": str(image_path)}},
        ],
    }

    content = build_doubao_video_generation_content(
        message,
        fallback_prompt="补充提示词",
    )

    assert content[0] == {"type": "text", "text": "补充提示词"}
    assert content[1]["type"] == "image_url"
    assert content[1]["role"] == "reference_image"
    assert content[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
