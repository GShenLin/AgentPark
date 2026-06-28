from src.providers.hyper3d_transport import download_bytes, request_json
from src.service_host import HostBoundService
from src.value_parsing import parse_optional_float_value


class Hyper3DRuntimeBase(HostBoundService):
    def _base_url(self):
        base_url = str(self.config.get("baseUrl") or "https://api.hyper3d.com/api/v2").strip().rstrip("/")
        if not base_url:
            raise ValueError("Hyper3D provider requires baseUrl.")
        return base_url

    def _api_url(self, endpoint):
        return f"{self._base_url()}/{str(endpoint or '').strip('/')}"

    def _headers(self, *, json_content=False, multipart_content_type=""):
        headers = {
            "Authorization": f"Bearer {self.config['apiKey']}",
            "accept": "application/json",
        }
        if json_content:
            headers["Content-Type"] = "application/json"
        if multipart_content_type:
            headers["Content-Type"] = multipart_content_type
        return headers

    def _timeout_sec(self):
        return float(self.config.get("timeoutMs", 60000)) / 1000.0

    def _request_json(self, *, url, method="POST", headers=None, body=None):
        return request_json(
            url=url,
            method=method,
            headers=headers or {},
            body=body,
            timeout_sec=self._timeout_sec(),
        )

    def _download_bytes(self, url):
        return download_bytes(url, timeout_sec=self._timeout_sec())

    def _resolve_poll_interval_seconds(self, *keys, default: float) -> float:
        for key in keys:
            value = self.config.get(key)
            if value not in {None, ""}:
                parsed = parse_optional_float_value(key, value, minimum_exclusive=0)
                return default if parsed is None else parsed
        return default

    def _resolve_max_wait_seconds(self, *keys, default: float) -> float | None:
        for key in keys:
            value = self.config.get(key)
            if value not in {None, ""}:
                return parse_optional_float_value(key, value, minimum_exclusive=0)
        return default
