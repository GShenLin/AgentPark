from __future__ import annotations

import base64
import hashlib
import mimetypes
import os
import secrets
import uuid
from urllib import error as urlerror
from urllib import parse, request

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.padding import PKCS7

from src.channels.errors import ChannelRuntimeError
from src.workspace_settings import get_workspace_root

from . import storage


WEIXIN_MEDIA_MAX_BYTES = 100 * 1024 * 1024


def aes_ecb_encrypt(plaintext: bytes, key: bytes) -> bytes:
    _require_aes_key(key)
    padder = PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def aes_ecb_decrypt(ciphertext: bytes, key: bytes) -> bytes:
    _require_aes_key(key)
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def aes_ecb_padded_size(plaintext_size: int) -> int:
    return ((int(plaintext_size) + 16) // 16) * 16


def parse_aes_key(value: object) -> bytes:
    raw = str(value or "").strip()
    if not raw:
        raise ChannelRuntimeError("aes_key is required")
    decoded = base64.b64decode(raw)
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            text = decoded.decode("ascii")
        except UnicodeDecodeError as exc:
            raise ChannelRuntimeError("aes_key base64 must decode to raw key or hex key") from exc
        if all(ch in "0123456789abcdefABCDEF" for ch in text):
            return bytes.fromhex(text)
    raise ChannelRuntimeError(f"aes_key must decode to 16 bytes or 32 hex chars, got {len(decoded)} bytes")


def build_cdn_download_url(encrypted_query_param: object, cdn_base_url: str) -> str:
    param = str(encrypted_query_param or "").strip()
    if not param:
        raise ChannelRuntimeError("encrypt_query_param is required")
    return f"{str(cdn_base_url or storage.DEFAULT_CDN_BASE_URL).rstrip('/')}/download?encrypted_query_param={parse.quote(param)}"


def build_cdn_upload_url(upload_param: object, filekey: str, cdn_base_url: str) -> str:
    param = str(upload_param or "").strip()
    if not param:
        raise ChannelRuntimeError("upload_param is required")
    return (
        f"{str(cdn_base_url or storage.DEFAULT_CDN_BASE_URL).rstrip('/')}/upload"
        f"?encrypted_query_param={parse.quote(param)}&filekey={parse.quote(filekey)}"
    )


def download_and_decrypt_image(image_item: dict, *, cdn_base_url: str, label: str = "image") -> tuple[str, str]:
    media = image_item.get("media") if isinstance(image_item.get("media"), dict) else {}
    full_url = str(media.get("full_url") or "").strip()
    url = full_url or build_cdn_download_url(media.get("encrypt_query_param"), cdn_base_url)
    aes_key_value = image_item.get("aeskey")
    if aes_key_value:
        try:
            key = bytes.fromhex(str(aes_key_value))
        except ValueError as exc:
            raise ChannelRuntimeError("image_item.aeskey must be hex") from exc
    elif media.get("aes_key"):
        key = parse_aes_key(media.get("aes_key"))
    else:
        key = b""
    encrypted = _download_bytes(url, label=label)
    payload = aes_ecb_decrypt(encrypted, key) if key else encrypted
    mime = guess_image_mime(payload)
    path = save_inbound_media(payload, mime=mime, prefix="weixin-image")
    return path, mime


def upload_image(
    *,
    file_path: str,
    to_user_id: str,
    base_url: str,
    token: str,
    cdn_base_url: str,
    get_upload_url,
) -> dict:
    local_path = resolve_local_path(file_path)
    if not os.path.exists(local_path) or not os.path.isfile(local_path):
        raise ChannelRuntimeError(f"image file does not exist: {local_path}")
    with open(local_path, "rb") as f:
        plaintext = f.read()
    if not plaintext:
        raise ChannelRuntimeError(f"image file is empty: {local_path}")
    if len(plaintext) > WEIXIN_MEDIA_MAX_BYTES:
        raise ChannelRuntimeError(f"image file is too large: {local_path}")

    rawsize = len(plaintext)
    filekey = secrets.token_hex(16)
    aeskey = secrets.token_bytes(16)
    upload_info = get_upload_url(
        base_url=base_url,
        token=token,
        filekey=filekey,
        media_type=1,
        to_user_id=to_user_id,
        rawsize=rawsize,
        rawfilemd5=hashlib.md5(plaintext).hexdigest(),
        filesize=aes_ecb_padded_size(rawsize),
        no_need_thumb=True,
        aeskey=aeskey.hex(),
    )
    upload_full_url = str(upload_info.get("upload_full_url") or "").strip()
    upload_param = str(upload_info.get("upload_param") or "").strip()
    upload_url = upload_full_url or build_cdn_upload_url(upload_param, filekey, cdn_base_url)
    download_param = _upload_encrypted_bytes(upload_url, aes_ecb_encrypt(plaintext, aeskey), label="image upload")
    return {
        "filekey": filekey,
        "downloadEncryptedQueryParam": download_param,
        "aeskey": aeskey.hex(),
        "fileSize": rawsize,
        "fileSizeCiphertext": aes_ecb_padded_size(rawsize),
        "mime": mimetypes.guess_type(local_path)[0] or guess_image_mime(plaintext),
    }


def save_inbound_media(payload: bytes, *, mime: str, prefix: str) -> str:
    ext = extension_from_mime(mime)
    media_dir = os.path.join(get_workspace_root(), "resource", "channel_media", "openclaw-weixin", "inbound")
    os.makedirs(media_dir, exist_ok=True)
    path = os.path.join(media_dir, f"{prefix}-{uuid.uuid4().hex}{ext}")
    with open(path, "wb") as f:
        f.write(payload)
    return path


def guess_image_mime(payload: bytes) -> str:
    if payload.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if payload.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if payload.startswith(b"GIF87a") or payload.startswith(b"GIF89a"):
        return "image/gif"
    if payload.startswith(b"RIFF") and payload[8:12] == b"WEBP":
        return "image/webp"
    if payload.startswith(b"BM"):
        return "image/bmp"
    return "image/jpeg"


def extension_from_mime(mime: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/bmp": ".bmp",
    }
    return mapping.get(str(mime or "").split(";")[0].strip().lower(), ".jpg")


def resolve_local_path(value: object) -> str:
    raw = str(value or "").strip()
    if raw.startswith("file://"):
        parsed = parse.urlparse(raw)
        path = parse.unquote(parsed.path)
        if os.name == "nt" and len(path) >= 3 and path[0] == "/" and path[2] == ":":
            path = path[1:]
        if parsed.netloc and parsed.netloc.lower() != "localhost":
            path = f"//{parsed.netloc}{path}"
        return os.path.abspath(os.path.expanduser(path))
    return os.path.abspath(os.path.expanduser(raw))


def _download_bytes(url: str, *, label: str) -> bytes:
    try:
        with request.urlopen(url, timeout=60) as resp:
            payload = resp.read()
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ChannelRuntimeError(f"{label} CDN download HTTP {exc.code}: {body}") from exc
    except urlerror.URLError as exc:
        raise ChannelRuntimeError(f"{label} CDN download failed: {exc}") from exc
    if len(payload) > WEIXIN_MEDIA_MAX_BYTES:
        raise ChannelRuntimeError(f"{label} CDN download exceeded {WEIXIN_MEDIA_MAX_BYTES} bytes")
    return payload


def _upload_encrypted_bytes(url: str, payload: bytes, *, label: str) -> str:
    req = request.Request(
        url,
        data=payload,
        headers={"Content-Type": "application/octet-stream"},
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=60) as resp:
            if resp.status != 200:
                raise ChannelRuntimeError(f"{label} CDN upload returned HTTP {resp.status}")
            download_param = resp.headers.get("x-encrypted-param")
    except urlerror.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ChannelRuntimeError(f"{label} CDN upload HTTP {exc.code}: {body}") from exc
    except urlerror.URLError as exc:
        raise ChannelRuntimeError(f"{label} CDN upload failed: {exc}") from exc
    if not download_param:
        raise ChannelRuntimeError(f"{label} CDN upload missing x-encrypted-param")
    return download_param


def _require_aes_key(key: bytes) -> None:
    if len(key) != 16:
        raise ChannelRuntimeError(f"AES-128-ECB key must be 16 bytes, got {len(key)}")
