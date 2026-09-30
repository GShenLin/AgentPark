from src.providers.curl_transport import CurlHttpTransport, CurlHttpError, CurlTransportError
import json
import mimetypes
import os
import uuid


def guess_mime_type(path):
    guessed, _ = mimetypes.guess_type(str(path or ""))
    return guessed or "application/octet-stream"


def request_json(*, url, method="POST", headers=None, body=None, timeout_sec=60):
    request = dict(url=url, body=body, headers=headers or {}, method=method)
    try:
        response = CurlHttpTransport().request(**request, timeout_sec=timeout_sec).raise_for_status()
        raw = response.content
    except CurlHttpError as exc:
        detail = exc.content.decode("utf-8", errors="replace")
        raise RuntimeError(f"Hyper3D HTTP {exc.status_code}: {detail}") from exc
    except Exception as exc:
        raise RuntimeError(f"Hyper3D request failed: {exc}") from exc

    text = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(text)
    except Exception as exc:
        raise RuntimeError(f"Invalid Hyper3D JSON response: {text[:500]}") from exc
    if isinstance(payload, dict) and payload.get("error"):
        raise RuntimeError(
            f"Hyper3D API error: {payload.get('error')}; message={payload.get('message')}"
        )
    return payload


def download_bytes(url, *, timeout_sec=60):
    try:
        response = CurlHttpTransport().request(url=str(url), timeout_sec=timeout_sec).raise_for_status()
        return response.content
    except Exception as exc:
        raise RuntimeError(f"Failed to download {url}: {exc}") from exc


def build_multipart_body(fields, files):
    boundary = f"----AgentParkHyper3D{uuid.uuid4().hex}"
    chunks: list[bytes] = []

    for name, value in fields:
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode("utf-8"))
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")

    for field_name, file_path in files:
        filename = os.path.basename(file_path)
        mime_type = guess_mime_type(file_path)
        chunks.append(f"--{boundary}\r\n".encode("utf-8"))
        chunks.append(
            (
                f'Content-Disposition: form-data; name="{field_name}"; filename="{filename}"\r\n'
                f"Content-Type: {mime_type}\r\n\r\n"
            ).encode("utf-8")
        )
        with open(file_path, "rb") as file_obj:
            chunks.append(file_obj.read())
        chunks.append(b"\r\n")

    chunks.append(f"--{boundary}--\r\n".encode("utf-8"))
    return b"".join(chunks), f"multipart/form-data; boundary={boundary}"
