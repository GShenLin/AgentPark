import base64
import json
from io import BytesIO
from types import SimpleNamespace

import pytest
from PIL import Image

from src.providers.curl_transport import CurlResponse
from src.providers.doubao_image_generation import DoubaoImageGeneration
from src.providers.doubao_image_stream import merge_seedream_stream_events
from src.providers.image_reference_validation import (
    validate_reference_dimensions,
    validate_reference_image_bytes,
)


def _png_bytes(size=(16, 16)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, (20, 40, 60)).save(output, format="PNG")
    return output.getvalue()


def _image_service(remote_content: bytes | None = None) -> DoubaoImageGeneration:
    host = SimpleNamespace(
        config={"maxRetries": 0, "retryDelaySec": 0},
        _curl_get_bytes_with_retry=lambda **_kwargs: remote_content,
    )
    return DoubaoImageGeneration(host)


def test_reference_image_dimension_contract_rejects_all_documented_bounds():
    assert validate_reference_dimensions(15, 15) == (15, 15)
    with pytest.raises(ValueError, match="greater than 14"):
        validate_reference_dimensions(14, 15)
    with pytest.raises(ValueError, match="aspect ratio"):
        validate_reference_dimensions(272, 16)
    with pytest.raises(ValueError, match="36000000"):
        validate_reference_dimensions(6001, 6000)


def test_reference_image_bytes_validate_format_dimensions_and_declared_mime():
    content = _png_bytes()
    info = validate_reference_image_bytes(content, declared_mime_type="image/png")

    assert info.mime_type == "image/png"
    assert (info.width, info.height) == (16, 16)
    assert info.byte_count == len(content)
    with pytest.raises(ValueError, match="declares image/jpeg but contains image/png"):
        validate_reference_image_bytes(content, declared_mime_type="image/jpeg")
    with pytest.raises(ValueError, match="decodable supported image"):
        validate_reference_image_bytes(b"not-an-image")


def test_reference_image_bytes_support_documented_heic_input():
    from pillow_heif import from_pillow

    output = BytesIO()
    from_pillow(Image.new("RGB", (16, 16), (20, 40, 60))).save(output)

    info = validate_reference_image_bytes(
        output.getvalue(),
        declared_mime_type="image/heic",
    )

    assert info.mime_type == "image/heic"
    assert (info.width, info.height) == (16, 16)


def test_reference_image_preparation_validates_local_data_and_remote_inputs(tmp_path):
    content = _png_bytes()
    local_path = tmp_path / "reference.png"
    local_path.write_bytes(content)
    data_url = f"data:image/png;base64,{base64.b64encode(content).decode('ascii')}"
    remote_url = "https://example.test/reference.png"
    service = _image_service(content)

    prepared = service._prepare_reference_images([str(local_path), data_url, remote_url])

    assert prepared[0].startswith("data:image/png;base64,")
    assert prepared[1] == data_url
    assert prepared[2] == remote_url


def test_reference_image_preparation_rejects_invalid_remote_pixels():
    service = _image_service(_png_bytes((14, 16)))

    with pytest.raises(ValueError, match="greater than 14"):
        service._prepare_reference_images("https://example.test/too-small.png")


def test_seedream_stream_events_merge_documented_success_failure_and_completion():
    events = [
        {
            "type": "image_generation.partial_succeeded",
            "model": "doubao-seedream-5-0-260128",
            "created": 123,
            "image_index": 0,
            "url": "https://example.test/output.png",
            "size": "2048x2048",
        },
        {
            "type": "image_generation.partial_failed",
            "model": "doubao-seedream-5-0-260128",
            "created": 123,
            "image_index": 1,
            "error": {"code": "OutputImageSensitiveContentDetected", "message": "blocked"},
        },
        {
            "type": "image_generation.completed",
            "model": "doubao-seedream-5-0-260128",
            "created": 123,
            "tools": [{"type": "web_search"}],
            "usage": {"generated_images": 1, "total_tokens": 16384},
        },
    ]

    result = merge_seedream_stream_events(events)

    assert result == {
        "data": [
            {
                "image_index": 0,
                "size": "2048x2048",
                "url": "https://example.test/output.png",
            },
            {
                "image_index": 1,
                "error": {"code": "OutputImageSensitiveContentDetected", "message": "blocked"},
            },
        ],
        "model": "doubao-seedream-5-0-260128",
        "created": 123,
        "tools": [{"type": "web_search"}],
        "usage": {"generated_images": 1, "total_tokens": 16384},
    }


def test_seedream_stream_events_require_documented_terminal_protocol():
    with pytest.raises(ValueError, match="Unsupported.*<empty>"):
        merge_seedream_stream_events([{"data": []}])
    with pytest.raises(ValueError, match="ended before"):
        merge_seedream_stream_events([{
            "type": "image_generation.partial_succeeded",
            "model": "model",
            "created": 123,
            "image_index": 0,
            "url": "https://example.test/output.png",
            "size": "2048x2048",
        }])


def test_image_service_parses_documented_sse_data_lines():
    events = [
        {
            "type": "image_generation.partial_succeeded",
            "model": "doubao-seedream-4-5-251128",
            "created": 456,
            "image_index": 0,
            "b64_json": base64.b64encode(b"image").decode("ascii"),
            "size": "2048x2048",
        },
        {
            "type": "image_generation.completed",
            "model": "doubao-seedream-4-5-251128",
            "created": 456,
            "usage": {"generated_images": 1},
        },
    ]
    host = SimpleNamespace(
        config={"timeoutMs": 60_000},
        _curl_post_sse_raw_lines=lambda **_kwargs: iter([
            *(json.dumps(event) for event in events),
            CurlResponse(body="", status_code=200),
        ]),
    )
    service = DoubaoImageGeneration(host)

    result = service._request_images(
        url="https://example.test/images/generations",
        headers={},
        payload_json="{}",
        stream=True,
        max_retries=0,
        retry_delay=0,
        timeout_ms=60_000,
    )

    assert result["data"][0]["b64_json"] == base64.b64encode(b"image").decode("ascii")
    assert result["usage"] == {"generated_images": 1}


def test_non_stream_image_request_uses_generation_timeout_and_retry_policy():
    captured = {}

    def post_json(**kwargs):
        captured.update(kwargs)
        return {"data": []}

    service = DoubaoImageGeneration(SimpleNamespace(
        config={"timeoutMs": 60_000, "imageGenerationTimeoutMs": 180_000},
        _post_json_with_retry=post_json,
    ))

    result = service._request_images(
        url="https://example.test/images/generations",
        headers={},
        payload_json="{}",
        stream=False,
        max_retries=0,
        retry_delay=1,
    )

    assert result == {"data": []}
    assert captured["timeout_ms"] == 180_000
    assert captured["max_retries"] == 0
