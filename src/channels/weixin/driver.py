from __future__ import annotations

import base64
import json
import random
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error as urlerror
from urllib import parse, request

from src.channels.errors import ChannelConfigError, ChannelRuntimeError
from src.message_protocol import build_resource_part, build_text_part, normalize_envelope

from . import storage
from .media import download_and_decrypt_image, upload_image


PLUGIN_VERSION = "2.4.4"
ILINK_APP_ID = "bot"
ILINK_CLIENT_VERSION = (2 << 16) | (4 << 8) | 4
DEFAULT_BOT_TYPE = "3"
DEFAULT_TIMEOUT_SECONDS = 15
DEFAULT_LONG_POLL_SECONDS = 35


@dataclass
class LoginSession:
    session_key: str
    qrcode: str
    qrcode_url: str
    started_at: float


class WeixinChannelDriver:
    channel_id = storage.CHANNEL_ID

    def __init__(self) -> None:
        self._login_sessions: dict[str, LoginSession] = {}

    def list_accounts(self) -> list[str]:
        return storage.list_account_ids()

    def start_login(self, *, account_id: str = "", force: bool = False) -> dict:
        session_key = storage.normalize_account_id(account_id) or uuid.uuid4().hex
        existing = self._login_sessions.get(session_key)
        if existing and not force and time.time() - existing.started_at < 300:
            return {
                "session_key": existing.session_key,
                "qrcode_url": existing.qrcode_url,
                "message": "QR code already exists for this login session.",
            }

        token_list = self._local_token_list()
        raw = self._post_raw(
            storage.DEFAULT_BASE_URL,
            f"ilink/bot/get_bot_qrcode?bot_type={parse.quote(DEFAULT_BOT_TYPE)}",
            {"local_token_list": token_list},
            token="",
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
        parsed = self._parse_json(raw, label="get_bot_qrcode")
        qrcode = str(parsed.get("qrcode") or "").strip()
        qrcode_url = str(parsed.get("qrcode_img_content") or "").strip()
        if not qrcode or not qrcode_url:
            raise ChannelRuntimeError("Weixin login did not return qrcode/qrcode_img_content")
        self._login_sessions[session_key] = LoginSession(
            session_key=session_key,
            qrcode=qrcode,
            qrcode_url=qrcode_url,
            started_at=time.time(),
        )
        return {
            "session_key": session_key,
            "qrcode_url": qrcode_url,
            "message": "Scan the QR code URL with Weixin, then call login_wait.",
        }

    def wait_login(self, *, session_key: str, timeout_seconds: int = 60) -> dict:
        key = str(session_key or "").strip()
        if not key:
            raise ChannelConfigError("session_key is required")
        login = self._login_sessions.get(key)
        if not login:
            raise ChannelRuntimeError("login session does not exist or has expired")
        timeout = max(1, min(int(timeout_seconds), 480))
        deadline = time.time() + timeout
        current_base_url = storage.DEFAULT_BASE_URL
        while time.time() < deadline:
            endpoint = f"ilink/bot/get_qrcode_status?qrcode={parse.quote(login.qrcode)}"
            raw = self._get_raw(current_base_url, endpoint, timeout_seconds=DEFAULT_LONG_POLL_SECONDS)
            parsed = self._parse_json(raw, label="get_qrcode_status")
            status = str(parsed.get("status") or "").strip()
            if status in {"wait", "scaned"}:
                time.sleep(1)
                continue
            if status == "scaned_but_redirect":
                redirect_host = str(parsed.get("redirect_host") or "").strip()
                if redirect_host:
                    current_base_url = f"https://{redirect_host}"
                time.sleep(1)
                continue
            if status == "expired":
                self._login_sessions.pop(key, None)
                return {"connected": False, "status": status, "message": "QR code expired."}
            if status == "binded_redirect":
                self._login_sessions.pop(key, None)
                return {"connected": True, "status": status, "message": "Account is already connected."}
            if status == "confirmed":
                token = str(parsed.get("bot_token") or "").strip()
                account_id = str(parsed.get("ilink_bot_id") or "").strip()
                if not token or not account_id:
                    raise ChannelRuntimeError("Weixin login confirmed without bot_token/ilink_bot_id")
                normalized = storage.save_account(
                    account_id,
                    token=token,
                    base_url=str(parsed.get("baseurl") or "").strip() or storage.DEFAULT_BASE_URL,
                    user_id=str(parsed.get("ilink_user_id") or "").strip(),
                )
                self._login_sessions.pop(key, None)
                return {
                    "connected": True,
                    "status": status,
                    "account_id": normalized,
                    "message": "Weixin account connected.",
                }
            raise ChannelRuntimeError(f"unsupported Weixin login status: {status}")
        return {"connected": False, "status": "timeout", "message": "Login wait timed out."}

    def get_updates(self, *, account_id: str, timeout_seconds: int = DEFAULT_LONG_POLL_SECONDS) -> dict:
        account = self._load_account(account_id)
        sync_buf = storage.load_sync_buf(account_id)
        raw = self._post_raw(
            account["baseUrl"],
            "ilink/bot/getupdates",
            {
                "get_updates_buf": sync_buf,
                "base_info": self._base_info(),
            },
            token=account["token"],
            timeout_seconds=max(1, min(int(timeout_seconds), 60)),
        )
        parsed = self._parse_json(raw, label="getupdates")
        ret = parsed.get("ret")
        errcode = parsed.get("errcode")
        if (ret is not None and ret != 0) or (errcode is not None and errcode != 0):
            raise ChannelRuntimeError(
                f"Weixin getupdates failed: ret={ret} errcode={errcode} errmsg={parsed.get('errmsg') or ''}"
            )
        next_buf = parsed.get("get_updates_buf")
        if next_buf is not None:
            storage.save_sync_buf(account_id, next_buf)
        return parsed

    def send_text(
        self,
        *,
        account_id: str,
        to_user_id: str,
        text: str,
        context_token: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        account = self._load_account(account_id)
        to_text = str(to_user_id or "").strip()
        body_text = str(text or "")
        if not to_text:
            raise ChannelConfigError("to_user_id is required")
        if not body_text.strip():
            raise ChannelConfigError("text is required")
        client_id = f"aitools-weixin-{uuid.uuid4().hex}"
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_text,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "item_list": [{"type": 1, "text_item": {"text": body_text}}],
                "context_token": str(context_token or "").strip() or None,
            },
            "base_info": self._base_info(),
        }
        self._post_raw(
            account["baseUrl"],
            "ilink/bot/sendmessage",
            payload,
            token=account["token"],
            timeout_seconds=max(1, min(int(timeout_seconds), 120)),
        )
        return {"message_id": client_id, "channel": self.channel_id}

    def send_image(
        self,
        *,
        account_id: str,
        to_user_id: str,
        file_path: str,
        context_token: str = "",
        timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS,
    ) -> dict:
        account = self._load_account(account_id)
        to_text = str(to_user_id or "").strip()
        if not to_text:
            raise ChannelConfigError("to_user_id is required")
        uploaded = upload_image(
            file_path=file_path,
            to_user_id=to_text,
            base_url=account["baseUrl"],
            token=account["token"],
            cdn_base_url=account["cdnBaseUrl"],
            get_upload_url=self._get_upload_url,
        )
        client_id = f"aitools-weixin-{uuid.uuid4().hex}"
        aes_key_for_wire = base64.b64encode(str(uploaded["aeskey"]).encode("ascii")).decode("ascii")
        payload = {
            "msg": {
                "from_user_id": "",
                "to_user_id": to_text,
                "client_id": client_id,
                "message_type": 2,
                "message_state": 2,
                "item_list": [
                    {
                        "type": 2,
                        "image_item": {
                            "media": {
                                "encrypt_query_param": uploaded["downloadEncryptedQueryParam"],
                                "aes_key": aes_key_for_wire,
                                "encrypt_type": 1,
                            },
                            "mid_size": uploaded["fileSizeCiphertext"],
                        },
                    }
                ],
                "context_token": str(context_token or "").strip() or None,
            },
            "base_info": self._base_info(),
        }
        self._post_raw(
            account["baseUrl"],
            "ilink/bot/sendmessage",
            payload,
            token=account["token"],
            timeout_seconds=max(1, min(int(timeout_seconds), 120)),
        )
        return {"message_id": client_id, "channel": self.channel_id}

    def message_to_envelope(self, *, account_id: str, message: dict) -> dict:
        if not isinstance(message, dict):
            raise ChannelRuntimeError("Weixin message must be an object")
        from_user_id = str(message.get("from_user_id") or "").strip()
        context_token = str(message.get("context_token") or "").strip()
        if from_user_id and context_token:
            storage.save_context_token(account_id, from_user_id, context_token)
        if from_user_id:
            storage.save_default_target(account_id, from_user_id, context_token)
        parts = []
        text = self._body_from_items(message.get("item_list"))
        if text:
            parts.append(build_text_part(text))
        resource_parts = self._resource_parts_from_items(message.get("item_list"), account_id=account_id)
        pending_image_parts = []
        if text and from_user_id:
            pending_image_parts = storage.consume_recent_image_context(account_id, from_user_id)
        if resource_parts and from_user_id and not text:
            storage.save_recent_image_context(account_id, from_user_id, resource_parts)
        parts.extend(pending_image_parts)
        parts.extend(resource_parts)
        return normalize_envelope({"role": "user", "parts": parts}, default_role="user")

    def _load_account(self, account_id: str) -> dict:
        resolved_id = storage.resolve_account_id(account_id)
        account = storage.load_account(resolved_id)
        if not isinstance(account, dict):
            raise ChannelConfigError(f"openclaw-weixin account is not logged in: {resolved_id}")
        token = str(account.get("token") or "").strip()
        if not token:
            raise ChannelConfigError(f"openclaw-weixin account token is missing: {resolved_id}")
        return {
            "accountId": resolved_id,
            "token": token,
            "baseUrl": str(account.get("baseUrl") or "").strip() or storage.DEFAULT_BASE_URL,
            "cdnBaseUrl": str(account.get("cdnBaseUrl") or "").strip() or storage.DEFAULT_CDN_BASE_URL,
        }

    def _local_token_list(self) -> list[str]:
        tokens: list[str] = []
        for account_id in storage.list_account_ids()[-10:]:
            account = storage.load_account(account_id)
            token = str((account or {}).get("token") or "").strip()
            if token:
                tokens.append(token)
        return tokens

    def _base_info(self) -> dict:
        return {"channel_version": PLUGIN_VERSION, "bot_agent": "AITools/0.1.0"}

    def _headers(self, token: str = "", *, auth: bool = True) -> dict:
        headers = {
            "Content-Type": "application/json",
            "iLink-App-Id": ILINK_APP_ID,
            "iLink-App-ClientVersion": str(ILINK_CLIENT_VERSION),
            "X-WECHAT-UIN": base64.b64encode(str(random.getrandbits(32)).encode("utf-8")).decode("ascii"),
        }
        if auth:
            headers["AuthorizationType"] = "ilink_bot_token"
        token_text = str(token or "").strip()
        if token_text:
            headers["Authorization"] = f"Bearer {token_text}"
        return headers

    def _post_raw(
        self,
        base_url: str,
        endpoint: str,
        payload: dict,
        *,
        token: str = "",
        timeout_seconds: int,
        auth: bool = True,
    ) -> str:
        url = self._join_url(base_url, endpoint)
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        req = request.Request(url, data=data, headers=self._headers(token, auth=auth), method="POST")
        return self._open(req, timeout_seconds=timeout_seconds)

    def _get_raw(self, base_url: str, endpoint: str, *, timeout_seconds: int) -> str:
        req = request.Request(self._join_url(base_url, endpoint), headers=self._headers("", auth=False), method="GET")
        return self._open(req, timeout_seconds=timeout_seconds)

    def _open(self, req: request.Request, *, timeout_seconds: int) -> str:
        try:
            with request.urlopen(req, timeout=timeout_seconds) as resp:
                return resp.read().decode("utf-8", errors="replace")
        except urlerror.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise ChannelRuntimeError(f"HTTP {exc.code} from Weixin API: {body}") from exc
        except urlerror.URLError as exc:
            raise ChannelRuntimeError(f"Weixin API request failed: {exc}") from exc

    @staticmethod
    def _join_url(base_url: str, endpoint: str) -> str:
        base = str(base_url or storage.DEFAULT_BASE_URL).rstrip("/") + "/"
        return parse.urljoin(base, str(endpoint or "").lstrip("/"))

    @staticmethod
    def _parse_json(raw: str, *, label: str) -> dict:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ChannelRuntimeError(f"{label} returned invalid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ChannelRuntimeError(f"{label} returned non-object JSON")
        return parsed

    def _get_upload_url(self, **kwargs) -> dict:
        payload = {
            "filekey": kwargs.get("filekey"),
            "media_type": kwargs.get("media_type"),
            "to_user_id": kwargs.get("to_user_id"),
            "rawsize": kwargs.get("rawsize"),
            "rawfilemd5": kwargs.get("rawfilemd5"),
            "filesize": kwargs.get("filesize"),
            "no_need_thumb": kwargs.get("no_need_thumb"),
            "aeskey": kwargs.get("aeskey"),
            "base_info": self._base_info(),
        }
        raw = self._post_raw(
            str(kwargs.get("base_url") or storage.DEFAULT_BASE_URL),
            "ilink/bot/getuploadurl",
            payload,
            token=str(kwargs.get("token") or ""),
            timeout_seconds=DEFAULT_TIMEOUT_SECONDS,
        )
        parsed = self._parse_json(raw, label="getuploadurl")
        ret = parsed.get("ret")
        errcode = parsed.get("errcode")
        if (ret is not None and ret != 0) or (errcode is not None and errcode != 0):
            raise ChannelRuntimeError(
                f"Weixin getuploadurl failed: ret={ret} errcode={errcode} errmsg={parsed.get('errmsg') or ''}"
            )
        return parsed

    def _body_from_items(self, items: Any) -> str:
        if not isinstance(items, list):
            return ""
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == 1 and isinstance(item.get("text_item"), dict):
                text = str((item.get("text_item") or {}).get("text") or "").strip()
                if text:
                    return text
            if item_type == 3 and isinstance(item.get("voice_item"), dict):
                text = str((item.get("voice_item") or {}).get("text") or "").strip()
                if text:
                    return text
        return ""

    def _resource_parts_from_items(self, items: Any, *, account_id: str) -> list[dict]:
        if not isinstance(items, list):
            return []
        image_items = [item for item in items if isinstance(item, dict) and item.get("type") == 2 and isinstance(item.get("image_item"), dict)]
        if not image_items:
            return []
        account = self._load_account(account_id)
        parts: list[dict] = []
        for item in image_items:
            image_item = item.get("image_item") or {}
            path, mime = download_and_decrypt_image(
                image_item,
                cdn_base_url=account["cdnBaseUrl"],
                label="inbound image",
            )
            parts.append(
                build_resource_part(
                    uri=path,
                    kind="image",
                    mime=mime,
                    name="weixin-image",
                )
            )
        return parts
