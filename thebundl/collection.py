"""HTML-only source collection primitives."""

from __future__ import annotations

import json

from bs4 import BeautifulSoup

from .schemas import ExtractedPage, Source


def extract_html(source: Source, html: str) -> ExtractedPage:
    """Extract text, links, and JSON-LD only; fetching is added later."""
    soup = BeautifulSoup(html, "html.parser")
    links = [anchor["href"] for anchor in soup.select("a[href]") if anchor["href"].startswith("http")]
    structured_data = []
    for node in soup.select('script[type="application/ld+json"]'):
        try:
            payload = json.loads(node.get_text())
            structured_data.append(payload if isinstance(payload, dict) else {"items": payload})
        except json.JSONDecodeError:
            continue
    return ExtractedPage(source_url=source.url, text=soup.get_text(" ", strip=True), links=links, structured_data=structured_data)
