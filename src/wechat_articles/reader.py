"""Bounded public WeChat link reading through AgentPark's shared transport."""
import time
from urllib.parse import urljoin, urlsplit

from src.providers.curl_transport import CurlHttpTransport
from .embedded import ArticleParseError
from .parser import Article, parse_article


def validate_url(url: str) -> str:
    if not isinstance(url, str) or not url or any(c.isspace() or ord(c) < 32 for c in url):
        raise ValueError("Expected a WeChat article URL without whitespace")
    parts = urlsplit(url)
    if (parts.scheme != "https" or parts.hostname != "mp.weixin.qq.com"
            or parts.port not in (None, 443) or parts.username or parts.password
            or not (parts.path == "/s" or parts.path.startswith("/s/"))):
        raise ValueError("Only HTTPS mp.weixin.qq.com/s article URLs are accepted")
    return url


def read_article(url: str) -> Article:
    current = validate_url(url)
    transport = CurlHttpTransport()
    deadline = time.monotonic() + 45
    for _ in range(4):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError("WeChat article fetch exceeded 45 seconds")
        response = transport.request(
            url=current, follow_redirects=False, timeout_sec=remaining,
            max_response_bytes=8 * 1024 * 1024,
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
                     "Accept": "text/html", "Accept-Language": "zh-CN,zh;q=0.9"},
        )
        if response.status_code in {301, 302, 303, 307, 308}:
            location = response.headers.get("location")
            if not location:
                raise ArticleParseError("WeChat redirect has no Location")
            current = validate_url(urljoin(current, location))
            continue
        if response.status_code != 200:
            raise ArticleParseError(f"WeChat returned HTTP {response.status_code}")
        content_type = response.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type not in {"text/html", "application/xhtml+xml"}:
            raise ArticleParseError(f"Expected HTML, received {content_type!r}")
        # WeChat serves UTF-8; don't let detector guesses damage Chinese/emoji.
        return parse_article(response.content.decode("utf-8-sig"), current)
    raise ArticleParseError("Too many WeChat article redirects")
