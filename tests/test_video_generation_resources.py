from nodes.video_generation_resources import merge_configured_video_resources


def test_merge_configured_video_resources_marks_roles():
    payload = merge_configured_video_resources(
        {"role": "user", "parts": []},
        first_frame_path="first.png",
        last_frame_path="last.png",
        reference_images=["ref-a.png"],
        reference_videos=["ref-b.mp4"],
        reference_audios=["ref-c.mp3"],
    )

    resources = [part["resource"] for part in payload["parts"] if part.get("type") == "resource"]
    assert [item.get("metadata", {}).get("role") for item in resources] == [
        "first_frame",
        "last_frame",
        "reference_image",
        "reference_video",
        "reference_audio",
    ]
