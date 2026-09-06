"""Playwright crawler used by the Streamlit translation checker."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from collections import deque
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlsplit, urlunsplit

try:
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from playwright.sync_api import sync_playwright
    PLAYWRIGHT_IMPORT_ERROR = ""
except ModuleNotFoundError as error:
    # Keep the Streamlit interface available so it can show a useful setup error.
    sync_playwright = None
    PlaywrightError = Exception
    PlaywrightTimeoutError = TimeoutError
    PLAYWRIGHT_IMPORT_ERROR = str(error)


NAVIGATION_TIMEOUT = 35_000
DEFAULT_HEADERS = {
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.5",
}


def normalize_url(value: str) -> str:
    value = value.strip()
    if not value:
        return ""
    if not re.match(r"^https?://", value, re.IGNORECASE):
        value = "https://" + value
    value, _ = urldefrag(value)
    parsed = urlsplit(value)
    query = [
        (key, item)
        for key, item in parse_qsl(parsed.query, keep_blank_values=True)
        if not key.casefold().startswith(("utm_", "fbclid", "gclid", "yclid"))
    ]
    value = urlunsplit((parsed.scheme, parsed.netloc, parsed.path, urlencode(query), ""))
    return value.rstrip("/") or value


def _same_domain(first: str, second: str) -> bool:
    left = (urlparse(first).hostname or "").casefold().removeprefix("www.")
    right = (urlparse(second).hostname or "").casefold().removeprefix("www.")
    return bool(left and left == right)


def _looks_like_product_url(url: str) -> bool:
    path = (urlparse(url).path or "").casefold()
    return (
        path.endswith(('.html', '.htm'))
        or any(marker in path for marker in ("/product/", "/products/", "/item/", "/goods/", "/p/"))
    )


def _looks_like_catalog_url(url: str) -> bool:
    if _looks_like_product_url(url):
        return False
    path = (urlparse(url).path or "").casefold()
    return any(marker in path.split("/") for marker in ("catalog", "catalogue", "category", "categories", "shop"))


NAV_LINK_SELECTOR = (
    "header a[href], nav a[href], footer a[href], [role='navigation'] a[href], "
    "[class*='header'] a[href], [class*='footer'] a[href]"
)


def _internal_links(page, base_url: str, selector: str = "a[href]") -> list[str]:
    links = page.eval_on_selector_all(
        selector,
        """
        elements => elements.filter(element => {
          const style = getComputedStyle(element);
          const rect = element.getBoundingClientRect();
          return style.display !== 'none' && style.visibility !== 'hidden' &&
            rect.width > 0 && rect.height > 0;
        }).map(element => element.href)
        """,
    )
    result: list[str] = []
    seen: set[str] = set()
    for raw_url in links:
        url = normalize_url(urljoin(base_url, str(raw_url)))
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not _same_domain(url, base_url):
            continue
        if re.search(r"\.(?:pdf|jpg|jpeg|png|gif|svg|webp|mp4|mp3|zip|rar)(?:$|\?)", parsed.path, re.IGNORECASE):
            continue
        if url in seen:
            continue
        seen.add(url)
        result.append(url)
    return result


def _expand_dynamic_content(page) -> None:
    selectors = [
        "button[aria-expanded='false']",
        "[role='button'][aria-expanded='false']",
        "summary",
        "[role='tab']",
        ".swiper-button-next",
        ".slick-next",
        ".owl-next",
        "button[aria-label*='next' i]",
        "button[title*='next' i]",
    ]
    for selector in selectors:
        try:
            locator = page.locator(selector)
            count = min(locator.count(), 80)
            for index in range(count):
                try:
                    item = locator.nth(index)
                    if item.is_visible(timeout=250):
                        item.click(timeout=900, force=True)
                        page.wait_for_timeout(100)
                except (PlaywrightError, PlaywrightTimeoutError):
                    continue
        except (PlaywrightError, PlaywrightTimeoutError):
            continue


def _scroll_to_end(page) -> None:
    last_height = 0
    for _ in range(12):
        height = page.evaluate("document.documentElement.scrollHeight")
        page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
        page.wait_for_timeout(350)
        new_height = page.evaluate("document.documentElement.scrollHeight")
        if new_height == last_height or new_height == height:
            break
        last_height = new_height
    page.evaluate("window.scrollTo(0, 0)")


def _collect_page(page, url: str, depth: int, expand_dynamic: bool, collect_links: bool = True) -> dict:
    page.goto(url, wait_until="domcontentloaded", timeout=NAVIGATION_TIMEOUT)
    page.wait_for_timeout(800)
    if expand_dynamic:
        _expand_dynamic_content(page)
    _scroll_to_end(page)
    if expand_dynamic:
        _expand_dynamic_content(page)
        _scroll_to_end(page)

    text = page.locator("body").inner_text(timeout=5_000)
    attributes = page.eval_on_selector_all(
        "[alt], [title], [placeholder], [aria-label]",
        """
        elements => elements.map(element => {
          const values = ['alt', 'title', 'placeholder', 'aria-label']
            .filter(name => element.hasAttribute(name))
            .map(name => `${name}: ${element.getAttribute(name)}`);
          return values.join(' | ');
        }).filter(Boolean).join(String.fromCharCode(10))
        """,
    )
    site_terms = page.eval_on_selector_all(
        "[class*='logo'], [id*='logo'], [data-brand], [itemprop='brand'], meta[property='og:site_name']",
        """
        elements => elements.map(element => (
          element.innerText || element.getAttribute('alt') ||
          element.getAttribute('aria-label') || element.getAttribute('content') || ''
        ).trim()).filter(Boolean).slice(0, 50)
        """,
    )
    model_selector = (
        "h1, [itemprop='name'], [class*='model'], [id*='model'], [class*='sku'], [class*='product-name']"
        if _looks_like_product_url(url)
        else "[itemprop='name'], [class*='model'], [id*='model'], [class*='sku'], [class*='product-name']"
    )
    model_terms = page.eval_on_selector_all(
        model_selector,
        """
        elements => elements.map(element => (
          element.innerText || element.getAttribute('content') || ''
        ).trim()).filter(Boolean).slice(0, 100)
        """,
    )
    title = page.title()
    description = page.locator("meta[name='description']").get_attribute("content") or ""
    try:
        screenshot = page.screenshot(full_page=False)
    except Exception:
        screenshot = None
    return {
        "url": url,
        "depth": depth,
        "title": title,
        "description": description,
        "text": text,
        "attributes": attributes,
        "site_terms": site_terms or [],
        "model_terms": model_terms or [],
        "screenshot": screenshot,
        "issues": [],
        "error": "",
        "links": _internal_links(page, url) if collect_links else [],
        "nav_links": _internal_links(page, url, NAV_LINK_SELECTOR) if collect_links else [],
    }


def _install_browser_if_needed() -> None:
    """Streamlit Community Cloud may not have the Playwright browser cache yet."""
    if sync_playwright is None:
        raise RuntimeError(
            "Не установлен Playwright. Добавьте requirements.txt в корень GitHub-репозитория "
            "рядом с app.py и перезапустите приложение."
        ) from ModuleNotFoundError(PLAYWRIGHT_IMPORT_ERROR)
    with sync_playwright() as playwright:
        executable = playwright.chromium.executable_path
    if os.path.exists(executable):
        return
    subprocess.run(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )


def crawl_site(
    start_url: str,
    max_depth: int | None = 0,
    max_pages: int | None = 20,
    product_sample: int = 3,
    expand_dynamic: bool = True,
    smart_mode: bool = True,
    progress=None,
    status=None,
) -> list[dict]:
    """Breadth-first crawl of one domain, returning one result per visited page."""
    start_url = normalize_url(start_url)
    if not start_url:
        raise ValueError("Не указана ссылка на сайт")
    if urlparse(start_url).scheme not in {"http", "https"}:
        raise ValueError("Ссылка должна начинаться с http:// или https://")

    if max_depth is not None:
        max_depth = max(0, min(int(max_depth), 3))
    if max_pages is not None:
        max_pages = max(1, min(int(max_pages), 500))
    product_sample = max(1, min(int(product_sample), 10))
    if _looks_like_product_url(start_url):
        start_kind = "product"
    else:
        start_kind = "catalog" if _looks_like_catalog_url(start_url) else "home"
    if not smart_mode:
        start_kind = "generic"
    queue = deque([(start_url, 0, start_kind)])
    queued = {start_url}
    results: list[dict] = []
    limit_reached = False

    _install_browser_if_needed()
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
            extra_http_headers=DEFAULT_HEADERS,
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(5_000)
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT)

        def enqueue(link: str, depth: int, kind: str) -> None:
            nonlocal limit_reached
            if (max_depth is not None and depth > max_depth) or link in queued:
                return
            if max_pages is not None and len(queued) >= max_pages:
                limit_reached = True
                return
            queued.add(link)
            queue.append((link, depth, kind))

        try:
            while queue and (max_pages is None or len(results) < max_pages):
                url, depth, kind = queue.popleft()
                if status:
                    total_label = "без лимита" if max_pages is None else str(max_pages)
                    status(f"Проверяется страница {len(results) + 1} из {total_label}: {url}")
                if progress and max_pages is not None:
                    progress(len(results) / max_pages)
                try:
                    result = _collect_page(page, url, depth, expand_dynamic)
                except Exception as error:
                    result = {
                        "url": url,
                        "depth": depth,
                        "title": "",
                        "description": "",
                        "text": "",
                        "attributes": "",
                        "site_terms": [],
                        "model_terms": [],
                        "screenshot": None,
                        "issues": [],
                        "error": str(error),
                        "links": [],
                        "nav_links": [],
                    }
                results.append(result)
                if smart_mode:
                    next_depth = depth + 1
                    if kind == "home":
                        # From the homepage follow only links a visitor can reach
                        # in the header/navigation/footer, plus visible catalog links.
                        for link in result.get("nav_links", []):
                            if _looks_like_catalog_url(link):
                                enqueue(link, next_depth, "catalog")
                            elif not _looks_like_product_url(link):
                                enqueue(link, next_depth, "nav")
                        for link in result.get("links", []):
                            if _looks_like_catalog_url(link):
                                enqueue(link, next_depth, "catalog")
                    elif kind == "nav":
                        # A header/footer page can lead to another catalog section,
                        # but its body links are not recursively crawled.
                        for link in result.get("nav_links", []):
                            if _looks_like_catalog_url(link):
                                enqueue(link, next_depth, "catalog")
                    elif kind == "catalog":
                        product_links_seen = 0
                        for link in result.get("links", []):
                            if _looks_like_catalog_url(link):
                                enqueue(link, next_depth, "catalog")
                            elif _looks_like_product_url(link):
                                if product_links_seen >= product_sample:
                                    continue
                                product_links_seen += 1
                                enqueue(link, next_depth, "product")
                else:
                    product_links_seen = 0
                    current_is_product = _looks_like_product_url(url)
                    for link in result.get("links", []):
                        link_is_product = _looks_like_product_url(link)
                        if link_is_product and current_is_product:
                            continue
                        if link_is_product:
                            if product_links_seen >= product_sample:
                                continue
                            product_links_seen += 1
                        enqueue(link, depth + 1, "generic")
                if progress and max_pages is not None:
                    progress(len(results) / max_pages)
        finally:
            context.close()
            browser.close()
    if results:
        results[0]["_limit_reached"] = limit_reached
    if status:
        if limit_reached or (max_pages is not None and len(results) >= max_pages and queue):
            status(f"Проверка остановлена на лимите: {len(results)} страниц")
        else:
            status(f"Проверка завершена: {len(results)} страниц")
    return results


def crawl_pages(
    urls: list[str],
    max_pages: int | None = 100,
    expand_dynamic: bool = True,
    progress=None,
    status=None,
    headers: dict[str, str] | None = None,
) -> list[dict]:
    """Visit only the supplied URLs; do not discover or enqueue new links."""
    clean_urls = []
    seen = set()
    for raw_url in urls:
        url = normalize_url(raw_url)
        if url and url not in seen:
            seen.add(url)
            clean_urls.append(url)
    if max_pages is not None:
        clean_urls = clean_urls[: max(0, int(max_pages))]

    _install_browser_if_needed()
    results: list[dict] = []
    total = len(clean_urls)
    request_headers = dict(DEFAULT_HEADERS)
    request_headers.update(headers or {})
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage", "--no-sandbox"],
        )
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            locale="ru-RU",
            extra_http_headers=request_headers,
            ignore_https_errors=True,
        )
        page = context.new_page()
        page.set_default_timeout(5_000)
        page.set_default_navigation_timeout(NAVIGATION_TIMEOUT)
        try:
            for index, url in enumerate(clean_urls):
                if status:
                    status(f"Проверяется страница {index + 1} из {total}: {url}")
                if progress and total:
                    progress(index / total)
                try:
                    result = _collect_page(page, url, index, expand_dynamic, collect_links=False)
                except Exception as error:
                    result = {
                        "url": url,
                        "depth": index,
                        "title": "",
                        "description": "",
                        "text": "",
                        "attributes": "",
                        "site_terms": [],
                        "model_terms": [],
                        "screenshot": None,
                        "issues": [],
                        "error": str(error),
                        "links": [],
                        "nav_links": [],
                    }
                results.append(result)
                if progress and total:
                    progress((index + 1) / total)
        finally:
            context.close()
            browser.close()
    if status:
        status(f"Проверка завершена: {len(results)} страниц")
    return results
