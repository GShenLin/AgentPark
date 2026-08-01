from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from src.image_matting import MagicWandMattingConfig, remove_connected_background


def _run_magic_wand(tmp_path, image: Image.Image, **overrides) -> tuple[dict, Image.Image]:
    source = tmp_path / "source.png"
    image.save(source)
    config = MagicWandMattingConfig.from_values(
        tolerance=overrides.get("tolerance", 1),
        edge_softness=overrides.get("edge_softness", 0),
        feather_px=overrides.get("feather_px", 0),
        background_color=overrides.get("background_color", ""),
    )
    result = remove_connected_background(
        image_path=str(source),
        output_dir=str(tmp_path / "output"),
        filename_prefix="subject",
        config=config,
    )
    with Image.open(result["image_path"]) as opened:
        output = opened.copy()
    return result, output


def test_magic_wand_removes_only_border_connected_background(tmp_path):
    source = Image.new("RGB", (40, 40), "white")
    draw = ImageDraw.Draw(source)
    draw.rectangle((8, 8, 31, 31), fill="black")
    draw.rectangle((14, 14, 25, 25), fill="white")

    result, output = _run_magic_wand(tmp_path, source)
    alpha = output.getchannel("A")

    assert alpha.getpixel((0, 0)) == 0
    assert alpha.getpixel((8, 8)) == 255
    assert alpha.getpixel((20, 20)) == 255
    assert result["background_color"] == "#FFFFFF"
    assert result["method"] == "magic_wand"


def test_magic_wand_feathers_the_hard_alpha_edge(tmp_path):
    source = Image.new("RGB", (48, 48), "white")
    ImageDraw.Draw(source).rectangle((12, 12, 35, 35), fill="black")

    _result, output = _run_magic_wand(tmp_path, source, feather_px=2)
    alpha_values = {
        value
        for value, count in enumerate(output.getchannel("A").histogram())
        if count
    }

    assert 0 in alpha_values
    assert 255 in alpha_values
    assert any(0 < value < 255 for value in alpha_values)


def test_magic_wand_reconstructs_antialiased_edge_and_removes_color_spill(
    tmp_path,
):
    background = (241, 241, 242)
    foreground = (233, 133, 30)
    source = Image.new("RGB", (9, 5), background)

    def blend(coverage: float) -> tuple[int, int, int]:
        return tuple(
            round(
                foreground[channel] * coverage
                + background[channel] * (1 - coverage)
            )
            for channel in range(3)
        )

    source.putpixel((2, 2), blend(0.25))
    source.putpixel((3, 2), blend(0.5))
    source.putpixel((4, 2), foreground)
    source.putpixel((5, 2), blend(0.5))
    source.putpixel((6, 2), blend(0.25))

    result, output = _run_magic_wand(
        tmp_path,
        source,
        tolerance=1,
        edge_softness=128,
        background_color="#F1F1F2",
    )
    alpha = output.getchannel("A")

    assert alpha.getpixel((0, 0)) == 0
    assert 0 < alpha.getpixel((2, 2)) < alpha.getpixel((3, 2)) < 255
    assert alpha.getpixel((4, 2)) == 255
    assert output.getpixel((2, 2))[:3] != source.getpixel((2, 2))
    assert max(
        abs(output.getpixel((2, 2))[channel] - background[channel])
        for channel in range(3)
    ) > max(
        abs(source.getpixel((2, 2))[channel] - background[channel])
        for channel in range(3)
    )
    assert result["edge_softness"] == 128
    assert result["soft_edge_pixels"] == 4


def test_magic_wand_auto_uses_multiple_corner_colors(tmp_path):
    source = Image.new("RGB", (40, 30), "#101030")
    ImageDraw.Draw(source).rectangle((20, 0, 39, 29), fill="#000018")
    ImageDraw.Draw(source).rectangle((12, 8, 27, 21), fill="white")

    result, output = _run_magic_wand(tmp_path, source, tolerance=0)
    alpha = output.getchannel("A")

    assert result["background_mode"] == "corners"
    assert result["background_color"] == ""
    assert result["background_colors"] == ["#101030", "#000018"]
    assert alpha.getpixel((0, 15)) == 0
    assert alpha.getpixel((39, 15)) == 0
    assert alpha.getpixel((20, 15)) == 255


def test_magic_wand_accepts_an_explicit_background_color(tmp_path):
    source = Image.new("RGB", (24, 24), "#F0F0F0")
    ImageDraw.Draw(source).rectangle((6, 6, 17, 17), fill="#202020")
    source.putpixel((0, 0), (255, 0, 0))

    result, output = _run_magic_wand(
        tmp_path,
        source,
        background_color="#F0F0F0",
        tolerance=0,
    )

    assert result["background_color"] == "#F0F0F0"
    assert result["background_colors"] == ["#F0F0F0"]
    assert result["background_mode"] == "explicit"
    assert output.getchannel("A").getpixel((23, 23)) == 0
    assert output.getchannel("A").getpixel((12, 12)) == 255


def test_magic_wand_returns_uniform_alpha_instead_of_rejecting_content(tmp_path):
    source = Image.new("RGB", (16, 12), "white")

    result, output = _run_magic_wand(tmp_path, source, tolerance=0)

    assert result["alpha_min"] == 0
    assert result["alpha_max"] == 0
    assert result["foreground_pixels"] == 0
    assert output.getchannel("A").getextrema() == (0, 0)


def test_magic_wand_returns_opaque_image_when_explicit_background_is_absent(tmp_path):
    source = Image.new("RGB", (16, 12), "red")

    result, output = _run_magic_wand(
        tmp_path,
        source,
        tolerance=0,
        background_color="#0000FF",
    )

    assert result["alpha_min"] == 255
    assert result["alpha_max"] == 255
    assert result["background_pixels"] == 0
    assert output.getchannel("A").getextrema() == (255, 255)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("tolerance", -1, "tolerance"),
        ("tolerance", 12.5, "tolerance"),
        ("edge_softness", 12.5, "edge_softness"),
        ("edge_softness", 256, "edge_softness"),
        ("feather_px", 33, "feather_px"),
        ("background_color", "white", "background_color"),
    ],
)
def test_magic_wand_rejects_invalid_config(field, value, message):
    values = {
        "tolerance": 1,
        "edge_softness": 0,
        "feather_px": 0,
        "background_color": "",
    }
    values[field] = value

    with pytest.raises(ValueError, match=message):
        MagicWandMattingConfig.from_values(**values)
