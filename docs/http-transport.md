# HTTP transport

Project-owned HTTP/HTTPS requests use the existing
`src.providers.curl_transport.CurlHttpTransport`. There is one public transport;
`curl_stream.py` contains its SSE process loop and `curl_types.py` its shared
response/error contracts. Do not add another HTTP client or compatibility shim.

`request` accepts explicit method, byte body, headers, connection/total timeouts,
redirect policy, proxy policy, optional cookie file and response-size bound.
Responses expose `content` bytes, UTF-8 `body`, lowercase headers, status and
`json()`. HTTP error responses remain available; call `raise_for_status()` where
the caller wants an exception. Requests are not automatically retried. Existing
provider JSON/SSE entry points remain on this same transport.

`request_async` runs the same exchange and cancels/reaps its curl process before
returning cancellation. Portal sessions use private temporary cookie files and
serialize exchanges. Cookie selection for WebSocket upgrades respects domain,
path, expiration and Secure. WebSockets and WebRTC retain their own transports.

TLS chain and hostname verification stay enabled. On Windows, the private-CA
portal explicitly requests curl's `--ssl-revoke-best-effort`: its CA has no CRL
distribution point. This tolerates missing revocation information while retaining
certificate validation and checks of available revocation information. Other
HTTP calls retain curl's default revocation policy. No `--insecure` fallback is
used. See https://curl.se/docs/manpage.html#--ssl-revoke-best-effort.

HTTP requests ignore curl configuration files; loopback and explicit
`trust_env=False` calls bypass proxies. SSE calls retain provider concurrency,
stream inactivity timeout and cancellation behavior. Ordinary exchanges have a
total deadline; active SSE streams use an inactivity deadline instead.

`tests/test_http_transport_boundary.py` rejects alternate HTTP client imports in
project runtime and deployment code. URL parsing/file-URI conversion, test
clients and third-party SDK internals are outside this boundary. SDKs such as
MCP can still install/use httpx internally.

Run transport integration tests with:

```
python -m pytest tests/test_http_transport_boundary.py tests/test_curl_http_integration.py tests/test_curl_transport.py -q
```

These tests use loopback servers and cover binary payloads, HTTP errors,
redirects, cookies, proxy bypass, response bounds, cancellation and SSE behavior.
