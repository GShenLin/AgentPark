from __future__ import annotations

from io import BytesIO

import pytest
from PIL import Image

from src.providers.provider_errors import ProviderProtocolError


def _rgba_png(*, alpha_values: tuple[int, int] = (0, 255)) -> bytes:
    image = Image.new("RGBA", (16, 16), (20, 40, 60, alpha_values[0]))
    image.putpixel((8, 8), (20, 40, 60, alpha_values[1]))
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def test_alpha_matting_output_contract_accepts_rgba_png_with_matching_headers():
    from src.providers.alpha_matting_provider import AlphaMattingProvider

    result = AlphaMattingProvider._validate_output(
        _rgba_png(),
        {
            "x-image-width": "16",
            "x-image-height": "16",
            "x-alpha-min": "0",
            "x-alpha-max": "255",
            "x-cuda-peak-memory-allocated-bytes": "1234",
        },
    )

    assert result == {
        "width": 16,
        "height": 16,
        "alpha_min": 0,
        "alpha_max": 255,
        "cuda_peak_memory_allocated_bytes": 1234,
    }


def test_alpha_matting_output_contract_rejects_opaque_png():
    from src.providers.alpha_matting_provider import AlphaMattingProvider

    with pytest.raises(ProviderProtocolError, match="no nontrivial alpha range"):
        AlphaMattingProvider._validate_output(
            _rgba_png(alpha_values=(255, 255)),
            {
                "x-image-width": "16",
                "x-image-height": "16",
                "x-alpha-min": "255",
                "x-alpha-max": "255",
            },
        )


def test_alpha_matting_output_contract_rejects_header_mismatch():
    from src.providers.alpha_matting_provider import AlphaMattingProvider

    with pytest.raises(ProviderProtocolError, match="does not match decoded value"):
        AlphaMattingProvider._validate_output(
            _rgba_png(),
            {
                "x-image-width": "15",
                "x-image-height": "16",
                "x-alpha-min": "0",
                "x-alpha-max": "255",
            },
        )


def test_alpha_matting_does_not_start_managed_runtime_for_protocol_failure(monkeypatch):
    from src.providers.alpha_matting_provider import AlphaMattingProvider

    provider = AlphaMattingProvider.__new__(AlphaMattingProvider)
    monkeypatch.setattr(
        provider,
        "_read_health",
        lambda: (_ for _ in ()).throw(ProviderProtocolError("wrong service")),
    )
    monkeypatch.setattr(
        provider,
        "_start_managed_runtime",
        lambda: pytest.fail("managed runtime must not start for a protocol failure"),
    )

    with pytest.raises(ProviderProtocolError, match="wrong service"):
        provider._ensure_service_ready()
