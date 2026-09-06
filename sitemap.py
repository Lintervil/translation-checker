"""Sitemap discovery without extra dependencies."""

from __future__ import annotations

import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from urllib.parse import urldefrag, urljoin, urlparse


DEFAULT_HEADERS = {"User-Agent": "TranslationQA/1.0 (+https://streamlit.io)"}
SERVICE_URL_RE = re.compile(
    r"/(?:ajax|admin|personal|auth|login|register|cart|basket|order|compare|favorite|search|print)(?:/|$)"
    r"|/filter/|/sort/|\.pdf(?:$|\?)|(?:^|[?&])PAGEN_[^=&]+",
    re.IGNORECASE,
)


def _fetch(url: str, headers: dict[str, str], timeout: int = 25) -> bytes:
    request = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return response.read(12 * 1024 * 1024)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].casefold()


def _children(element: ET.Element, name: str) -> list[ET.Element]:
    return [child for child in list(element) if _local_name(child.tag) == name]


def _text(element: ET.Element | None, name: str) -> str:
    if element is None:
        return ""
    child = next((item for item in list(element) if _local_name(item.tag) == name), None)
    return (child.text or "").strip() if child is not None else ""


def _same_domain(first: str, second: str) -> bool:
    left = (urlparse(first).hostname or "").casefold().removeprefix("www.")
    right = (urlparse(second).hostname or "").casefold().removeprefix("www.")
    return bool(left and left == right)


def _clean_url(raw_url: str, base_url: str) -> str:
    url, _ = urldefrag(urljoin(base_url, raw_url.strip()))
    return url.rstrip("/") or url


def _is_allowed_page(url: str, start_url: str) -> bool:
    parsed = urlparse(url)
    return (
        parsed.scheme in {"http", "https"}
        and _same_domain(url, start_url)
        and not SERVICE_URL_RE.search(url)
    )


def get_sitemap_pages(
    start_url: str,
    headers: dict[str, str] | None,
    max_pages: int = 100,
) -> list[dict]:
    """Discover and rank same-domain URLs from robots.txt and sitemap files."""
    start_url = _clean_url(start_url, start_url)
    parsed = urlparse(start_url)
    if not parsed.netloc:
        return []

    request_headers = dict(DEFAULT_HEADERS)
    request_headers.update(headers or {})
    origin = f"{parsed.scheme}://{parsed.netloc}"
    sitemap_urls: list[str] = []
    try:
        robots = _fetch(f"{origin}/robots.txt", request_headers).decode("utf-8", errors="replace")
        for line in robots.splitlines():
            if line.casefold().startswith("sitemap:"):
                sitemap_url = _clean_url(line.split(":", 1)[1].strip(), origin)
                if sitemap_url and _same_domain(sitemap_url, start_url) and sitemap_url not in sitemap_urls:
                    sitemap_urls.append(sitemap_url)
    except (OSError, urllib.error.URLError, UnicodeError):
        pass
    if not sitemap_urls:
        sitemap_urls.append(f"{origin}/sitemap.xml")

    visited: set[str] = set()
    pages: dict[str, dict] = {}
    pending = list(sitemap_urls)
    while pending and len(visited) < 50:
        sitemap_url = pending.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)
        try:
            root = ET.fromstring(_fetch(sitemap_url, request_headers))
        except (OSError, urllib.error.URLError, ET.ParseError, UnicodeError):
            continue

        root_name = _local_name(root.tag)
        if root_name == "sitemapindex":
            for item in _children(root, "sitemap"):
                child_url = _clean_url(_text(item, "loc"), sitemap_url)
                if (
                    child_url
                    and _same_domain(child_url, start_url)
                    and child_url not in visited
                    and len(visited) + len(pending) < 50
                ):
                    pending.append(child_url)
            continue
        if root_name != "urlset":
            continue

        for item in _children(root, "url"):
            page_url = _clean_url(_text(item, "loc"), start_url)
            if not page_url or not _is_allowed_page(page_url, start_url):
                continue
            priority_text = _text(item, "priority")
            try:
                priority = float(priority_text)
            except (TypeError, ValueError):
                priority = 0.0
            lastmod = _text(item, "lastmod")
            candidate = {"url": page_url, "priority": priority, "lastmod": lastmod}
            existing = pages.get(page_url)
            if existing is None or (priority, lastmod) > (existing["priority"], existing["lastmod"]):
                pages[page_url] = candidate

    ranked = sorted(
        pages.values(),
        key=lambda item: (item["priority"], item["lastmod"]),
        reverse=True,
    )
    return ranked[: max(0, int(max_pages))]
