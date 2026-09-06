"""Detection of untranslated English text in Russian website content."""

from __future__ import annotations

import re
from collections import Counter
from typing import Iterable
from urllib.parse import urlparse

from exceptions import BASE_EXCEPTIONS


ENGLISH_RUN_RE = re.compile(
    r"(?<![A-Za-z])"
    r"(?:[A-Za-z][A-Za-z0-9]*(?:[._/+&'-][A-Za-z0-9]+)*)"
    r"(?:\s+(?:[A-Za-z][A-Za-z0-9]*(?:[._/+&'-][A-Za-z0-9]+)*)){0,6}"
    r"(?![A-Za-z])"
)
TOKEN_RE = re.compile(r"[A-Za-z][A-Za-z0-9]*(?:[._/+&'-][A-Za-z0-9]+)*")
URL_RE = re.compile(r"(?:https?://|www\.)\S+|\S+@[\w.-]+\.[A-Za-z]{2,}")
DOMAIN_SUFFIXES = {"com", "ru", "net", "org", "info", "рф"}
FILE_SUFFIXES = {
    "jpg", "jpeg", "png", "gif", "svg", "webp", "mp4", "mp3", "avi",
    "pdf", "doc", "docx", "xls", "xlsx", "zip", "rar", "csv", "json",
}
GENERIC_SITE_TERMS = {
    "www", "shop", "store", "online", "official", "site", "home", "main",
    "catalog", "ru", "com", "net", "org", "info",
}


def parse_exceptions(value: str | Iterable[str] | None) -> set[str]:
    """Return a normalized set from comma/newline/semicolon separated terms."""
    if not value:
        return set()
    if isinstance(value, str):
        values = re.split(r"[,;\n]+", value)
    else:
        values = value
    return {str(item).strip().casefold() for item in values if str(item).strip()}


def automatic_exceptions(start_url: str, pages: list[dict]) -> set[str]:
    """Build a conservative whitelist for a site's brand and product/model names."""
    values: list[str] = []
    host = urlparse(start_url).hostname or ""
    values.extend(re.findall(r"[A-Za-z][A-Za-z0-9-]{2,}", host))
    for page in pages:
        values.extend(page.get("site_terms", []))
        values.extend(page.get("model_terms", []))

    result: set[str] = set()
    for value in values:
        for match in ENGLISH_RUN_RE.finditer(str(value)):
            phrase = match.group(0).strip(" .,:;!?\"'«»()[]{}")
            if not phrase:
                continue
            tokens = TOKEN_RE.findall(phrase)
            if not tokens:
                continue
            if phrase.casefold() not in GENERIC_SITE_TERMS:
                result.add(phrase.casefold())
            # Keep standalone brand/model tokens useful inside mixed phrases,
            # but do not whitelist short generic UI words automatically.
            for token in tokens:
                if token.casefold() in GENERIC_SITE_TERMS or len(token) < 3:
                    continue
                if any(char.isdigit() for char in token) or token[:1].isupper() or token.isupper():
                    result.add(token.casefold())
    return result


def _is_inside_translation_parentheses(text: str, start: int, end: int) -> bool:
    before = text[:start]
    open_index = before.rfind("(")
    close_index = before.rfind(")")
    if open_index <= close_index:
        return False
    if text.find(")", end) < 0:
        return False
    before_parenthesis = before[:open_index]
    return bool(re.search(r"[А-Яа-яЁё]", before_parenthesis[-120:]))


def _is_technical_identifier(candidate: str, text: str, start: int, end: int) -> bool:
    lower = candidate.casefold()
    if len(candidate) == 1:
        return True
    if any(marker in lower for marker in ("://", "@")):
        return True
    if start and text[start - 1] == "/":
        return True
    if end < len(text) and text[end] == "/":
        return True
    if "." in candidate and candidate.rsplit(".", 1)[-1].casefold() in DOMAIN_SUFFIXES | FILE_SUFFIXES:
        return True
    if (start and text[start - 1].isdigit()) or (end < len(text) and text[end].isdigit()):
        return True
    if any(char.isdigit() for char in candidate):
        return True
    if re.fullmatch(r"[A-Z]{2,}(?:[-/][A-Z0-9]+)*", candidate):
        return True
    # Energy classes such as A+ and B++ are product specifications.
    if re.fullmatch(r"[A-Za-z]{1,2}\+{1,3}", candidate):
        return True
    if lower in DOMAIN_SUFFIXES:
        return True
    return False


def _context(text: str, start: int, end: int, radius: int = 62) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    value = re.sub(r"\s+", " ", text[left:right]).strip()
    if left:
        value = "..." + value
    if right < len(text):
        value += "..."
    return value


def find_english_issues(
    text: str,
    source: str,
    custom_exceptions: str | Iterable[str] | None = None,
    limit: int = 200,
) -> list[dict[str, str]]:
    """Find English words or phrases that are not in the technical whitelist."""
    if not text:
        return []

    allowlist = {item.casefold() for item in BASE_EXCEPTIONS} | parse_exceptions(custom_exceptions)
    issues: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()

    for match in ENGLISH_RUN_RE.finditer(text):
        candidate = match.group(0).strip(" .,:;!?\"'«»()[]{}")
        if not candidate or _is_technical_identifier(candidate, text, match.start(), match.end()):
            continue
        tokens = TOKEN_RE.findall(candidate)
        if not tokens:
            continue
        if candidate.casefold() in allowlist:
            continue
        candidate_for_tokens = candidate
        for allowed_phrase in sorted(
            (item for item in allowlist if " " in item),
            key=len,
            reverse=True,
        ):
            candidate_for_tokens = re.sub(
                rf"(?<![A-Za-z]){re.escape(allowed_phrase)}(?![A-Za-z])",
                " ",
                candidate_for_tokens,
                flags=re.IGNORECASE,
            )
        unknown = [
            token for token in TOKEN_RE.findall(candidate_for_tokens)
            if token.casefold() not in allowlist
        ]
        if not unknown or _is_inside_translation_parentheses(text, match.start(), match.end()):
            continue

        # Keep phrases such as "Buy now" together, but remove a whitelisted brand
        # from a mixed match such as "Samsung collection".
        term = " ".join(unknown)
        key = (term.casefold(), source, _context(text, match.start(), match.end()).casefold())
        if key in seen:
            continue
        seen.add(key)
        issues.append(
            {
                "word": term,
                "context": _context(text, match.start(), match.end()),
                "source": source,
            }
        )
        if len(issues) >= limit:
            break
    return issues


def check_page(page: dict, custom_exceptions: str | Iterable[str] | None = None) -> list[dict[str, str]]:
    """Analyze visible text, attributes, title and description from one crawl result."""
    exceptions = parse_exceptions(custom_exceptions)
    issues: list[dict[str, str]] = []
    issues.extend(find_english_issues(page.get("text", ""), "Видимый текст", exceptions))
    attributes = re.sub(
        r"(?:^|\n)(?:alt|title|placeholder|aria-label):\s*",
        "\n",
        page.get("attributes", ""),
        flags=re.IGNORECASE,
    )
    issues.extend(find_english_issues(attributes, "Атрибуты интерфейса", exceptions))
    issues.extend(find_english_issues(page.get("title", ""), "HTML title", exceptions))
    issues.extend(find_english_issues(page.get("description", ""), "Meta description", exceptions))

    unique: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for issue in issues:
        key = (issue["word"].casefold(), issue["source"], issue["context"].casefold())
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique


def top_words(pages: list[dict]) -> list[tuple[str, int]]:
    counter = Counter(
        issue["word"].casefold()
        for page in pages
        for issue in page.get("issues", [])
    )
    return counter.most_common(10)
