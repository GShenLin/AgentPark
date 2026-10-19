import json

from src.providers.curl_transport import CurlHttpTransport, CurlTransportError


class LocalHttp:
    def __init__(self, endpoint: str, api_key: str = ""):
        self.endpoint = endpoint
        self.headers = {"Content-Type": "application/json"}
        if api_key:
            self.headers["Authorization"] = "Bearer " + api_key
        self.transport = CurlHttpTransport()

    def request(self, path: str, body: dict | None = None, timeout: float = 5):
        response = self.transport.request(
            url=self.endpoint + path, method="GET" if body is None else "POST",
            headers=self.headers, body=None if body is None else json.dumps(body).encode(),
            timeout_sec=timeout, connect_timeout=2, follow_redirects=False, trust_env=False,
            max_response_bytes=16 * 1024 * 1024,
        )
        if not 200 <= response.status_code < 300:
            raise RuntimeError(f"{path}: HTTP {response.status_code} {response.body[:500]}")
        if not response.body.strip():
            return {}
        return json.loads(response.body)

    def probe(self, path: str) -> tuple[object | None, str]:
        try:
            return self.request(path), ""
        except (CurlTransportError, RuntimeError, ValueError) as exc:
            return None, str(exc)

    def probe_status(self, path: str) -> tuple[bool, str]:
        """Explicit HTTP readiness check; a successful response need not be JSON."""
        try:
            response = self.transport.request(
                url=self.endpoint + path, method="GET", timeout_sec=2, connect_timeout=1,
                follow_redirects=False, trust_env=False, max_response_bytes=1024 * 1024,
            )
        except CurlTransportError as exc:
            return False, str(exc)
        if not 200 <= response.status_code < 300:
            return False, f"{path}: HTTP {response.status_code}"
        return True, ""
