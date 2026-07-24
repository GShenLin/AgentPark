"""Volcengine HMAC-SHA256 OpenAPI transport used by speech management."""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import urllib.error
import urllib.parse
import urllib.request


class VolcengineOpenApi:
    def __init__(
        self,
        *,
        access_key_id: str,
        secret_access_key: str,
        region: str = "cn-north-1",
        service: str = "speech_saas_prod",
        domain: str = "open.volcengineapi.com",
        timeout: float = 60,
    ) -> None:
        self.access_key_id = str(access_key_id or "").strip()
        self.secret_access_key = str(secret_access_key or "").strip()
        self.region = str(region or "cn-north-1").strip()
        self.service = str(service or "speech_saas_prod").strip()
        self.domain = str(domain or "open.volcengineapi.com").strip()
        self.timeout = max(1.0, float(timeout))
        if not self.access_key_id or not self.secret_access_key:
            raise ValueError("Volcengine OpenAPI requires speechAccessKeyId and speechSecretAccessKey.")

    def post_json(self, action: str, version: str, payload: dict) -> dict:
        if not isinstance(payload, dict):
            raise ValueError("Volcengine OpenAPI payload must be an object.")
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        return self._request(action, version, body, "application/json; charset=utf-8")

    def _request(self, action: str, version: str, body: bytes, content_type: str) -> dict:
        query = urllib.parse.urlencode(sorted({"Action": action, "Version": version}.items()))
        now = dt.datetime.now(dt.timezone.utc)
        x_date = now.strftime("%Y%m%dT%H%M%SZ")
        day = now.strftime("%Y%m%d")
        payload_hash = hashlib.sha256(body).hexdigest()
        canonical_headers = (
            f"content-type:{content_type}\n"
            f"host:{self.domain}\n"
            f"x-content-sha256:{payload_hash}\n"
            f"x-date:{x_date}\n"
        )
        signed_headers = "content-type;host;x-content-sha256;x-date"
        canonical_request = "\n".join([
            "POST", "/", query, canonical_headers, signed_headers, payload_hash,
        ])
        scope = f"{day}/{self.region}/{self.service}/request"
        string_to_sign = "\n".join([
            "HMAC-SHA256",
            x_date,
            scope,
            hashlib.sha256(canonical_request.encode("utf-8")).hexdigest(),
        ])
        signing_key = self._sign(
            self._sign(self._sign(self._sign(self.secret_access_key.encode("utf-8"), day), self.region), self.service),
            "request",
        )
        signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
        authorization = (
            f"HMAC-SHA256 Credential={self.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        )
        request = urllib.request.Request(
            f"https://{self.domain}/?{query}",
            data=body,
            method="POST",
            headers={
                "Content-Type": content_type,
                "Host": self.domain,
                "X-Date": x_date,
                "X-Content-Sha256": payload_hash,
                "Authorization": authorization,
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                raw = response.read()
                status = int(getattr(response, "status", 200))
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = int(exc.code)
        except urllib.error.URLError as exc:
            raise ValueError(f"Volcengine OpenAPI request failed: {exc.reason}") from exc
        try:
            result = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError(f"Volcengine OpenAPI returned invalid JSON (HTTP {status}).") from exc
        if not isinstance(result, dict):
            raise ValueError("Volcengine OpenAPI response must be a JSON object.")
        metadata = result.get("ResponseMetadata")
        error = metadata.get("Error") if isinstance(metadata, dict) else None
        if not 200 <= status < 300 or isinstance(error, dict):
            code = str(error.get("Code") or "") if isinstance(error, dict) else ""
            message = str(error.get("Message") or "") if isinstance(error, dict) else ""
            raise ValueError(f"Volcengine OpenAPI {action} failed (HTTP {status}, {code or 'unknown'}): {message}")
        return result

    @staticmethod
    def _sign(key: bytes, value: str) -> bytes:
        return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()
