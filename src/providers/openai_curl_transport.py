import json

from src.providers.curl_transport import CurlResponse, CurlTransportError
from src.providers.curl_transport import CurlHttpTransport
from src.providers.openai_transport_errors import OpenAIHttpError, OpenAITransportError


class OpenAICurlTransport(CurlHttpTransport):
    def _curl_post_json_once(self, *, url, headers, payload_json, timeout_sec):
        try:
            response = self._curl_post_once_raw(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__OPENAI_HTTP_CODE__:",
            )
        except CurlTransportError as exc:
            raise OpenAITransportError(str(exc)) from exc

        if response.status_code < 200 or response.status_code >= 300:
            self._write_responses_http_debug(
                url=url,
                payload_json=payload_json,
                status_code=response.status_code,
                response_body=response.body,
            )
            raise OpenAIHttpError(response.status_code, response.body)
        try:
            return json.loads(response.body)
        except Exception as exc:
            raise RuntimeError(f"Invalid JSON response: {exc}; body={response.body[:500]}") from exc

    def _curl_post_sse_data_lines(self, *, url, headers, payload_json, timeout_sec):
        try:
            for item in self._curl_post_sse_raw_lines(
                url=url,
                headers=headers,
                payload_json=payload_json,
                timeout_sec=timeout_sec,
                marker="__OPENAI_HTTP_CODE__:",
            ):
                if isinstance(item, CurlResponse):
                    if item.status_code < 200 or item.status_code >= 300:
                        self._write_responses_http_debug(
                            url=url,
                            payload_json=payload_json,
                            status_code=item.status_code,
                            response_body=item.body,
                        )
                        raise OpenAIHttpError(item.status_code, item.body)
                    continue
                yield item
        except CurlTransportError as exc:
            raise OpenAITransportError(str(exc)) from exc
