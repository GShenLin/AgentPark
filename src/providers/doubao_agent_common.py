import json
import re


class _CurlHTTPError(RuntimeError):
    def __init__(self, status_code, response_body):
        self.status_code = int(status_code or 0)
        self.response_body = str(response_body or "")
        super().__init__(f"HTTP Error {self.status_code}: {self.response_body}")


class _CurlTransportError(RuntimeError):
    pass


def _parse_doubao_error_payload(response_body):
    text = str(response_body or "").strip()
    if not text:
        return {}
    try:
        payload = json.loads(text)
    except Exception:
        return {}
    if not isinstance(payload, dict):
        return {}
    error_obj = payload.get("error")
    return error_obj if isinstance(error_obj, dict) else {}


def _extract_request_id(error_message):
    text = str(error_message or "").strip()
    if not text:
        return ""
    match = re.search(r"Request id:\s*([A-Za-z0-9_-]+)", text)
    if not match:
        return ""
    return str(match.group(1) or "").strip()


def format_doubao_http_error(status_code, response_body):
    code = int(status_code or 0)
    text = str(response_body or "").strip()
    error_obj = _parse_doubao_error_payload(text)
    error_code = str(error_obj.get("code") or "").strip()
    error_message = str(error_obj.get("message") or "").strip()
    request_id = _extract_request_id(error_message)

    if error_code == "InputImageSensitiveContentDetected.PrivacyInformation":
        base = (
            "模型拒绝处理这张输入图片：检测到图片可能包含真人或隐私信息。"
            "当前视频生成不支持把真人照片作为参考图、首帧或尾帧。"
            "请改用非真人素材、虚拟角色，或去除人脸/隐私信息后重试。"
        )
        if request_id:
            return f"{base} [code={error_code}] [request_id={request_id}]"
        return f"{base} [code={error_code}]"

    if error_code and error_message:
        if request_id:
            return f"HTTP Error {code}: {error_code}: {error_message} [request_id={request_id}]"
        return f"HTTP Error {code}: {error_code}: {error_message}"
    return f"HTTP Error {code}: {text}"
