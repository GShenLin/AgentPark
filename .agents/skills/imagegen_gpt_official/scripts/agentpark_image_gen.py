#!/usr/bin/env python3
from __future__ import annotations

import base64
import json
import os
from pathlib import Path
import sys
import urllib.error
import urllib.request
import uuid


MODEL = "gpt-image-2.5"
MAX_IMAGE_BYTES = 50 * 1024 * 1024


def main() -> int:
    arguments = _arguments()
    prompt = str(arguments.get("prompt") or "").strip()
    if not prompt:
        raise ValueError("prompt is required")
    workspace_root = Path(__file__).resolve().parents[3]
    node_directory_text = str(os.environ.get("AGENTPARK_NODE_DIRECTORY") or "").strip()
    if not node_directory_text:
        raise ValueError("AgentPark node directory is unavailable")
    node_directory = Path(node_directory_text).resolve()
    if not node_directory.is_dir():
        raise ValueError(f"AgentPark node directory does not exist: {node_directory}")
    if not workspace_root.is_dir():
        raise ValueError("AgentPark workspace root is unavailable")

    sys.path.insert(0, str(workspace_root))
    from src.provider_auth.codex_oauth import RESPONSES_BASE_URL, refresh_authorization

    authorization = refresh_authorization()
    request_headers = {
        "Authorization": f"Bearer {authorization.access_token}",
        "ChatGPT-Account-ID": authorization.account_id,
    }
    references = _reference_images(arguments.get("referenced_image_paths"))
    if references:
        endpoint = "images/edits"
        payload = {
            "images": [{"image_url": item} for item in references],
            "prompt": prompt,
            "model": MODEL,
            "background": "auto",
            "quality": "auto",
            "size": "auto",
        }
    else:
        endpoint = "images/generations"
        payload = {
            "prompt": prompt,
            "model": MODEL,
            "background": "auto",
            "quality": "auto",
            "size": "auto",
        }
    result = _post_json(
        f"{RESPONSES_BASE_URL.rstrip('/')}/{endpoint}",
        request_headers,
        payload,
    )
    data = result.get("data") if isinstance(result, dict) else None
    if not isinstance(data, list) or not data or not isinstance(data[0], dict):
        raise ValueError("image endpoint response is missing data[0]")
    encoded = str(data[0].get("b64_json") or "").strip()
    if not encoded:
        raise ValueError("image endpoint response is missing data[0].b64_json")
    image_bytes = base64.b64decode(encoded, validate=True)
    if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("generated image has an invalid size")
    extension = _extension(image_bytes)
    output_dir = (node_directory / "generated_images").resolve()
    if node_directory not in output_dir.parents:
        raise ValueError("generated image directory escapes the AgentPark node directory")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"imagegen-{uuid.uuid4().hex}{extension}"
    output_path.write_bytes(image_bytes)
    print(json.dumps({"status": "success", "image_path": str(output_path)}, ensure_ascii=False))
    return 0


def _arguments() -> dict:
    raw = str(os.environ.get("AGENTPARK_SKILL_SCRIPT_ARGS") or "").strip()
    if not raw:
        raw = sys.stdin.read().strip()
    value = json.loads(raw or "{}")
    if not isinstance(value, dict):
        raise ValueError("tool arguments must be an object")
    return value


def _reference_images(value: object) -> list[str]:
    paths = value if isinstance(value, list) else []
    output: list[str] = []
    for raw in paths:
        path = Path(str(raw or "")).resolve()
        if not path.is_file():
            raise ValueError(f"referenced image does not exist: {path}")
        image_bytes = path.read_bytes()
        if not image_bytes or len(image_bytes) > MAX_IMAGE_BYTES:
            raise ValueError(f"referenced image has an invalid size: {path}")
        mime = _mime(image_bytes)
        output.append(f"data:{mime};base64,{base64.b64encode(image_bytes).decode('ascii')}")
    return output


def _post_json(url: str, headers: dict[str, str], payload: dict) -> dict:
    request_headers = {
        "Content-Type": "application/json",
        "originator": "codex_cli_rs",
        "User-Agent": "codex_cli_rs/0.0.0 (Windows; x86_64) AgentPark",
        **headers,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=request_headers,
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=290) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:4000]
        raise RuntimeError(f"image endpoint returned HTTP {exc.code}: {detail}") from exc
    if not isinstance(result, dict):
        raise ValueError("image endpoint response must be an object")
    return result


def _mime(data: bytes) -> str:
    return {".png": "image/png", ".jpg": "image/jpeg", ".webp": "image/webp"}[_extension(data)]


def _extension(data: bytes) -> str:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return ".jpg"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return ".webp"
    raise ValueError("image data has an unsupported signature")


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(json.dumps({"status": "error", "error": f"{type(exc).__name__}: {exc}"}, ensure_ascii=False))
        raise SystemExit(1)
