from src.providers.curl_transport import CurlResponse, CurlTransportError
from src.providers.curl_transport import CurlHttpTransport
from src.providers.doubao_agent_common import _CurlHTTPError, _CurlTransportError


class DoubaoCurlStreamTransport(CurlHttpTransport):
    def _curl_post_sse_data_lines(self, *, url: str, headers: dict, payload_json: str, timeout_sec: float):
        try:
            for item in self._curl_post_sse_raw_lines(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__DOUBAO_HTTP_CODE__:",
            ):
                if isinstance(item, CurlResponse):
                    if item.status_code != 200:
                        raise _CurlHTTPError(item.status_code, item.body)
                    continue
                yield item
        except CurlTransportError as exc:
            raise _CurlTransportError(str(exc)) from exc
