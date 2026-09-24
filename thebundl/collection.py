"""Safe HTML-only source collection primitives."""

from __future__ import annotations

import json
import hashlib
import ipaddress
import socket
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup
import httpx

from .discovery import normalize_url
from .config import Settings
from .observability import request_event
from .schemas import ExtractedPage, Source


def extract_html(source: Source, html: str) -> ExtractedPage:
    """Extract only text, links, and JSON-LD from collected HTML."""
    soup = BeautifulSoup(html, "html.parser")
    structured_data = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.get_text())
            structured_data.append(payload if isinstance(payload, dict) else {"items": payload})
        except json.JSONDecodeError:
            continue
    for tag in soup(["script", "style", "noscript", "template"]):
        tag.decompose()
    links = []
    for anchor in soup.select("a[href]"):
        try:
            link = normalize_url(urljoin(str(source.url), anchor["href"]))
        except ValueError:
            continue
        links.append(link)
    return ExtractedPage(source_url=source.url, text=soup.get_text(" ", strip=True), links=links,
                         structured_data=structured_data)


@dataclass(frozen=True)
class CollectionResult:
    source: Source
    page: ExtractedPage | None
    reason: str | None = None


def _public_host(url: str, resolver: Callable[..., object] = socket.getaddrinfo) -> bool:
    """Reject literal or DNS-resolved loopback/private/link-local destinations."""
    host = urlsplit(url).hostname
    if not host:
        return False
    try:
        addresses = [ipaddress.ip_address(host)]
    except ValueError:
        try:
            addresses = [ipaddress.ip_address(item[4][0]) for item in resolver(host, None)]
        except OSError:
            return False
    return bool(addresses) and all(not (address.is_private or address.is_loopback or address.is_link_local
                                        or address.is_reserved or address.is_unspecified)
                                   for address in addresses)


def _fetch_html(url: str, client: httpx.Client, *, resolver: Callable[..., object]) -> tuple[str | None, str | None, str | None]:
    """Fetch with manual, revalidated redirects; return html, final URL, reason."""
    current = url
    for _ in range(6):
        if not _public_host(current, resolver):
            return None, None, "unsafe destination"
        try:
            # Inspect headers before reading a body, so media/PDF responses are
            # closed without downloading their contents.
            with request_event("HTML fetch"), client.stream("GET", current, follow_redirects=False) as response:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        return None, None, "redirect without location"
                    try:
                        current = normalize_url(urljoin(current, location))
                    except ValueError:
                        return None, None, "unsafe redirect"
                    continue
                if response.status_code != 200:
                    return None, None, f"HTTP {response.status_code}"
                content_type = response.headers.get("content-type", "").split(";", 1)[0].casefold()
                if content_type not in {"text/html", "application/xhtml+xml"}:
                    return None, None, "unsupported content type (HTML required)"
                response.read()
                return response.text, normalize_url(str(response.url)), None
        except httpx.HTTPError as error:
            return None, None, f"request failed: {error.__class__.__name__}"
    return None, None, "too many redirects"


def collect_source(source: Source, *, client: httpx.Client, resolver: Callable[..., object] = socket.getaddrinfo) -> CollectionResult:
    """Collect one original HTML source, never rendering or downloading media."""
    html, final_url, reason = _fetch_html(str(source.url), client, resolver=resolver)
    if html is None or final_url is None:
        return CollectionResult(source, None, reason)
    resolved = source.model_copy(update={"url": final_url})
    page = extract_html(resolved, html)
    digest = hashlib.sha256(" ".join(page.text.split()).encode("utf-8")).hexdigest()
    return CollectionResult(resolved.model_copy(update={"content_hash": digest}), page)


def relevant_promotion_links(page: ExtractedPage, *, maximum: int = 5) -> list[str]:
    """Keep at most five same-site links likely to contain promotion details."""
    if maximum <= 0:
        return []
    origin = urlsplit(str(page.source_url)).hostname
    links: list[str] = []
    for link in page.links:
        parsed = urlsplit(str(link))
        if parsed.hostname != origin or not any(word in parsed.path.casefold() for word in
                                                 ("deal", "special", "offer", "promotion", "happy-hour")):
            continue
        if str(link) not in links:
            links.append(str(link))
        if len(links) == maximum:
            break
    return links


def should_process_content(content_hash: str, successful_hashes: set[str]) -> bool:
    """Only successful prior processing suppresses repeat AI work; failures are retryable."""
    return content_hash not in successful_hashes


def collect_sources(sources: list[Source], *, client: httpx.Client, maximum_links: int = 5,
                    pace_seconds: float = 0.0, sleep: Callable[[float], None] = time.sleep,
                    resolver: Callable[..., object] = socket.getaddrinfo) -> list[CollectionResult]:
    """Collect known sources and at most five relevant same-site pages per source."""
    results: list[CollectionResult] = []
    last_request: dict[str, float] = {}
    for source in sources:
        queue = [source]
        while queue:
            current = queue.pop(0)
            domain = urlsplit(str(current.url)).hostname or ""
            elapsed = time.monotonic() - last_request.get(domain, float("-inf"))
            if last_request.get(domain) is not None and elapsed < pace_seconds:
                sleep(pace_seconds - elapsed)
            result = collect_source(current, client=client, resolver=resolver)
            last_request[domain] = time.monotonic()
            results.append(result)
            if current is source and result.page:
                queue.extend(Source(url=link, title=source.title, discovered_at=source.discovered_at,
                                    campus=source.campus, priority=source.priority)
                             for link in relevant_promotion_links(result.page, maximum=maximum_links))
    return results


def _processing_cache_path(settings: Settings) -> Path:
    return settings.work_dir / "successful-content-hashes.json"


def successful_content_hashes(settings: Settings) -> set[str]:
    path = _processing_cache_path(settings)
    return set(json.loads(path.read_text(encoding="utf-8"))) if path.exists() else set()


def record_successful_processing(settings: Settings, content_hash: str) -> None:
    """Persist only success, so a failed model call is naturally retried later."""
    hashes = successful_content_hashes(settings)
    hashes.add(content_hash)
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    _processing_cache_path(settings).write_text(json.dumps(sorted(hashes), indent=2) + "\n", encoding="utf-8")
