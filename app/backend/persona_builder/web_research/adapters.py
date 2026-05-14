from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import hashlib
import re
from typing import Protocol
from urllib.parse import parse_qs, quote_plus, unquote, urlparse, urlunparse

import httpx


@dataclass(frozen=True)
class SearchCandidate:
    url: str
    title: str = ""
    snippet: str = ""
    channel: str = "basic_search"


@dataclass(frozen=True)
class CrawledPage:
    url: str
    final_url: str
    title: str
    markdown: str
    text: str
    content_hash: str
    warning: str = ""


class SearchProvider(Protocol):
    def search(self, query: str, *, limit: int) -> list[SearchCandidate]:
        ...


class WebCrawler(Protocol):
    def crawl(self, url: str) -> CrawledPage:
        ...


class BasicSearchProvider:
    """A small no-key fallback searcher.

    This is intentionally conservative. Production deployments can replace it with AutoSearch MCP
    or another first-class search provider while keeping the same source/provenance contract.
    """

    def __init__(self, *, timeout_seconds: float = 20) -> None:
        self.timeout_seconds = timeout_seconds

    def search(self, query: str, *, limit: int) -> list[SearchCandidate]:
        if not query.strip():
            return []
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "WebVirtualPersonaResearch/1.0"},
            ) as client:
                response = client.get(
                    "https://duckduckgo.com/html/",
                    params={"q": query},
                )
                response.raise_for_status()
        except Exception:
            return []
        return _parse_duckduckgo_html(response.text, limit=limit)


class BasicCrawler:
    def __init__(self, *, timeout_seconds: float = 60) -> None:
        self.timeout_seconds = timeout_seconds

    def crawl(self, url: str) -> CrawledPage:
        try:
            with httpx.Client(
                timeout=self.timeout_seconds,
                follow_redirects=True,
                headers={"User-Agent": "WebVirtualPersonaResearch/1.0"},
            ) as client:
                response = client.get(url)
                response.raise_for_status()
        except Exception as exc:
            return CrawledPage(
                url=url,
                final_url=url,
                title="",
                markdown="",
                text="",
                content_hash="",
                warning=f"抓取失败：{exc.__class__.__name__}",
            )
        content_type = response.headers.get("content-type", "")
        text = response.text
        if "html" in content_type.lower() or "<html" in text[:1000].lower():
            title, body = html_to_text(text)
        else:
            title, body = "", text
        body = normalize_space(body)
        title = title or urlparse(str(response.url)).netloc
        markdown = f"# {title}\n\nSource: {response.url}\n\n{body}".strip()
        return CrawledPage(
            url=url,
            final_url=str(response.url),
            title=normalize_space(title)[:240],
            markdown=markdown[:180000],
            text=body[:160000],
            content_hash=sha256_text(body),
        )


class _ReadableHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.title_parts: list[str] = []
        self.parts: list[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3", "br"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False
        if tag in {"p", "div", "section", "article", "li", "tr", "h1", "h2", "h3"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth:
            return
        text = unescape(data)
        if self._in_title:
            self.title_parts.append(text)
        self.parts.append(text)


def html_to_text(html: str) -> tuple[str, str]:
    parser = _ReadableHTMLParser()
    try:
        parser.feed(html)
    except Exception:
        plain = re.sub(r"<[^>]+>", " ", html)
        return "", normalize_space(unescape(plain))
    title = normalize_space(" ".join(parser.title_parts))
    body = normalize_space(" ".join(parser.parts))
    return title, body


def canonical_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower() or "https"
    host = parsed.netloc.lower()
    if host.startswith("www."):
        host = host[4:]
    path = re.sub(r"/+$", "", parsed.path or "/")
    return urlunparse((scheme, host, path, "", "", ""))


def source_id_for(url: str, content_hash: str = "") -> str:
    base = canonical_url(url) + "|" + (content_hash or "")
    return "websrc_" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def normalize_space(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\x00", " ")).strip()


def _parse_duckduckgo_html(html: str, *, limit: int) -> list[SearchCandidate]:
    candidates: list[SearchCandidate] = []
    pattern = re.compile(
        r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
        re.I | re.S,
    )
    for match in pattern.finditer(html):
        href = unescape(match.group("href"))
        title = normalize_space(re.sub(r"<[^>]+>", " ", unescape(match.group("title"))))
        url = _unwrap_duckduckgo_url(href)
        if not url.startswith(("http://", "https://")):
            continue
        candidates.append(SearchCandidate(url=url, title=title, channel="duckduckgo_html"))
        if len(candidates) >= limit:
            break
    return candidates


def _unwrap_duckduckgo_url(href: str) -> str:
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.query:
        values = parse_qs(parsed.query).get("uddg")
        if values:
            return unquote(values[0])
    if href.startswith("//duckduckgo.com/l/"):
        values = parse_qs(urlparse("https:" + href).query).get("uddg")
        if values:
            return unquote(values[0])
    return href


def direct_search_url(query: str) -> str:
    return f"https://duckduckgo.com/html/?q={quote_plus(query)}"
