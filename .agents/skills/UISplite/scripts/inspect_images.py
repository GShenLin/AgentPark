"""Read-only image/alpha diagnostics; CLI or AgentPark skill arguments."""
from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys


def inspect_image(path_text: str, min_margin: float | None) -> dict:
    from PIL import Image

    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError(f"image path must be absolute: {path_text}")
    with Image.open(path) as image:
        image.load()
        has_alpha = "A" in image.getbands() or "transparency" in image.info
        alpha = image.convert("RGBA").getchannel("A")
        histogram = alpha.histogram()
        total = image.width * image.height
        visible = total - histogram[0]
        bbox = alpha.getbbox()
        body_bbox = alpha.point(lambda value: 255 if value > 127 else 0).getbbox()
        margins = None
        if body_bbox:
            left, top, right, bottom = body_bbox
            margins = {
                "left": left / image.width, "top": top / image.height,
                "right": (image.width - right) / image.width,
                "bottom": (image.height - bottom) / image.height,
            }
        margin_pass = None
        if min_margin is not None:
            margin_pass = bool(margins and min(margins.values()) >= min_margin)
        return {
            "file": str(path.resolve()), "format": image.format,
            "size": [image.width, image.height], "mode": image.mode,
            "has_alpha_or_transparent_color": has_alpha,
            "alpha_min_max": list(alpha.getextrema()),
            "has_fully_transparent_pixels": histogram[0] > 0,
            "has_visible_pixels": visible > 0,
            "transparent_percent": round(histogram[0] / total * 100, 3),
            "partial_alpha_percent": round(sum(histogram[1:255]) / total * 100, 3),
            "opaque_percent": round(histogram[255] / total * 100, 3),
            "visible_alpha_250_to_255_percent": (
                round(sum(histogram[250:]) / visible * 100, 3) if visible else None
            ),
            "alpha_bbox": bbox, "body_bbox_alpha_gt_127": body_bbox,
            "body_margin_fractions": margins,
            "requested_min_margin_fraction": min_margin,
            "body_margin_pass": margin_pass,
        }


def read_arguments() -> tuple[list[str], float | None]:
    raw = os.environ.get("AGENTPARK_SKILL_SCRIPT_ARGS")
    if raw is not None:
        arguments = json.loads(raw)
        if not isinstance(arguments, dict):
            raise ValueError("tool arguments must be an object")
        unknown = set(arguments) - {"image_paths", "min_margin_fraction"}
        if unknown:
            raise ValueError(f"unknown arguments: {sorted(unknown)}")
        paths = arguments.get("image_paths")
        margin = arguments.get("min_margin_fraction")
    else:
        parser = argparse.ArgumentParser(description=__doc__)
        parser.add_argument("image_paths", nargs="+")
        parser.add_argument("--min-margin-fraction", type=float)
        args = parser.parse_args()
        paths, margin = args.image_paths, args.min_margin_fraction
    if not isinstance(paths, list) or not paths or not all(
        isinstance(path, str) and path.strip() for path in paths
    ):
        raise ValueError("image_paths must be a nonempty list of file paths")
    if margin is not None:
        if type(margin) not in (int, float) or not math.isfinite(margin) or not 0 <= margin < 0.5:
            raise ValueError("min_margin_fraction must be finite and in [0, 0.5)")
    return paths, margin


def main() -> int:
    try:
        paths, margin = read_arguments()
        results = [inspect_image(path, margin) for path in paths]
    except (ValueError, OSError, ImportError) as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(json.dumps({"status": "success", "images": results}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
