"""WeChat HTML/body and picture-post adapters with an explicit output contract."""
from dataclasses import asdict, dataclass
from html import unescape
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
from markdownify import markdownify

from .embedded import ArticleParseError, article_data, elements, members, string_literal


@dataclass(frozen=True)
class Article:
    source_url: str
    title: str
    account: str | None
    author: str | None
    published_at: str | None
    format: str
    markdown: str
    images: list[str]
    warnings: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _url(value: str, base: str) -> str | None:
    value = urljoin(base, unescape(value).strip())
    parts = urlsplit(value)
    if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password:
        return None
    return value


def _field(data: dict[str, str], name: str) -> str | None:
    if name not in data:
        return None
    value = unescape(string_literal(data[name])).strip()
    return value or None


def parse_article(html: str, url: str) -> Article:
    soup = BeautifulSoup(html, "html.parser")
    body = soup.select_one("#js_content, .rich_media_content")
    if body is not None:
        def text(selector: str) -> str | None:
            tag = soup.select_one(selector)
            return tag.get_text(" ", strip=True) or None if tag else None

        title = text("#activity-name")
        if not title:
            meta = soup.select_one('meta[property="og:title"]')
            title = str(meta.get("content", "")).strip() if meta else None
        if not title:
            raise ArticleParseError("Article body exists but title is missing")
        for tag in body.select("script, style, noscript, iframe"):
            tag.decompose()
        images = []
        warnings = []
        for img in body.select("img"):
            src = _url(str(img.get("data-src") or img.get("src") or ""), url)
            if src and (img.get("data-src") or img.get("src")):
                img["src"] = src
                if src not in images:
                    images.append(src)
            else:
                warnings.append("An image has no supported HTTP(S) source and was omitted.")
                img.decompose()
        for link in body.select("a[href]"):
            href = _url(str(link["href"]), url)
            if href:
                link["href"] = href
            else:
                del link["href"]
        if body.select("mpvideo, mpvoice, qqmusic, mp-common-videosnap"):
            warnings.append("Embedded audio/video is not transcribed.")
        markdown = markdownify(str(body), heading_style="ATX").strip()
        if not markdown:
            raise ArticleParseError("Article body is empty")
        if images:
            warnings.append("Image URLs are preserved; image text has not been OCRed.")
        return Article(url, title, text("#js_name"), text("#js_author_name"),
                       text("#publish_time"), "article", markdown, images, warnings)

    data = article_data([tag.string or tag.get_text() for tag in soup.find_all("script")])
    if data is not None and "picture_page_info_list" in data and "content_noencode" in data:
        # Use full post text, never the potentially shortened `desc` preview.
        title = _field(data, "title")
        if not title:
            raise ArticleParseError("Picture post title is missing")
        content = _field(data, "content_noencode") or ""
        images = []
        for raw in elements(data["picture_page_info_list"]):
            value = _field(members(raw), "cdn_url")
            src = _url(value, url) if value else None
            if not src:
                raise ArticleParseError("Picture post contains an invalid image URL")
            images.append(src)
        if not content and not images:
            raise ArticleParseError("Picture post has neither text nor images")
        pictures = "\n\n".join(f"![配图 {i}](<{src}>)" for i, src in enumerate(images, 1))
        markdown = "\n\n".join(part for part in (content, pictures) if part)
        warnings = ["Image URLs are preserved; image text has not been OCRed."] if images else []
        return Article(url, title, _field(data, "nick_name"), _field(data, "author"),
                       _field(data, "create_time"), "picture_post", markdown, images, warnings)

    # A successful HTTP response can still be an access challenge or deleted post.
    raise ArticleParseError("No supported WeChat article body: the page may require verification, "
                            "be unavailable, or use an unsupported template. No page chrome was returned as article text.")
