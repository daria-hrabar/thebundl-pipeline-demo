"""Brave-backed, budgeted source discovery; results are leads, not evidence."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .config import Settings
from .deduplication import deduplicate_sources
from .schemas import Source

_TRACKING_PARAMETERS = {"fbclid", "gclid", "dclid", "msclkid", "mc_cid", "mc_eid"}
_NEIGHBORHOODS = {
    "baruch": ("Kips Bay", "Gramercy", "Murray Hill", "Flatiron", "NoMad", "Union Square"),
    "columbia": ("Morningside Heights", "Harlem", "Manhattanville", "Upper West Side"),
}


class SearchClient(Protocol):
    def search(self, query: str, *, count: int) -> list[dict[str, str]]: ...


class BraveSearchClient:
    """Adapter kept separate so fixture-backed clients can be used in tests."""

    def __init__(self, api_key: str, *, client: httpx.Client | None = None) -> None:
        self.api_key = api_key
        self.client = client or httpx.Client(timeout=15.0)

    def search(self, query: str, *, count: int) -> list[dict[str, str]]:
        response = self.client.get(
            "https://api.search.brave.com/res/v1/web/search", params={"q": query, "count": count},
            headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
        )
        response.raise_for_status()
        return [{"url": item["url"], "title": item.get("title", "")}
                for item in response.json().get("web", {}).get("results", []) if item.get("url")]


def normalize_url(value: str) -> str:
    """Remove only known tracking parameters; preserve useful query and branch paths."""
    parsed = urlsplit(value)
    scheme, host = parsed.scheme.lower(), (parsed.hostname or "").lower()
    if scheme not in {"http", "https"} or not host:
        raise ValueError("source URLs must be absolute HTTP(S) URLs")
    netloc = host if parsed.port is None else f"{host}:{parsed.port}"
    query = urlencode([(key, item) for key, item in parse_qsl(parsed.query, keep_blank_values=True)
                       if key.casefold() not in _TRACKING_PARAMETERS
                       and not key.casefold().startswith("utm_")], doseq=True)
    return urlunsplit((scheme, netloc, parsed.path or "/", query, ""))


def discovery_queries() -> list[tuple[str, str]]:
    """Aggregator-oriented queries for both coverage areas and neighborhoods."""
    queries: list[tuple[str, str]] = []
    for campus, neighborhoods in _NEIGHBORHOODS.items():
        area = "Baruch College" if campus == "baruch" else "Columbia University Morningside"
        queries.append((campus, f"{area} NYC food deals happy hour specials restaurants"))
        queries.extend((campus, f"{neighborhood} NYC restaurant food deals specials") for neighborhood in neighborhoods)
    return queries


def _ledger_path(settings: Settings) -> Path:
    return settings.work_dir / "discovery-ledger.json"


def _sources_path(settings: Settings) -> Path:
    return settings.work_dir / "known-sources.json"


def known_sources(settings: Settings) -> list[Source]:
    """Load reusable discovered sources; no network access is involved."""
    path = _sources_path(settings)
    return [Source.model_validate(item) for item in json.loads(path.read_text(encoding="utf-8"))] if path.exists() else []


def _save_sources(settings: Settings, sources: list[Source]) -> None:
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    _sources_path(settings).write_text(
        json.dumps([source.model_dump(mode="json") for source in sources], indent=2) + "\n", encoding="utf-8"
    )


def _load_ledger(settings: Settings) -> dict[str, Any]:
    path = _ledger_path(settings)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {
        "search_spend_usd": 0.0, "last_discovery_at": None,
    }


def _save_ledger(settings: Settings, ledger: dict[str, Any]) -> None:
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    _ledger_path(settings).write_text(json.dumps(ledger, indent=2) + "\n", encoding="utf-8")


def discovery_due(settings: Settings, *, now: datetime | None = None) -> bool:
    last = _load_ledger(settings).get("last_discovery_at")
    if not last:
        return True
    return (now or datetime.now(UTC)) - datetime.fromisoformat(last) >= timedelta(days=settings.discovery_interval_days)


def discover_sources(settings: Settings, limit: int, *, search_client: SearchClient | None = None,
                     now: datetime | None = None) -> list[Source]:
    """Discover normalized source leads without fetching, extraction, or publishing."""
    if limit < 1:
        return []
    if search_client is None:
        if settings.brave_search_api_key is None:
            raise RuntimeError("BRAVE_SEARCH_API_KEY is required for discovery")
        search_client = BraveSearchClient(settings.brave_search_api_key.get_secret_value())
    ledger = _load_ledger(settings)
    spend, timestamp = float(ledger.get("search_spend_usd", 0.0)), now or datetime.now(UTC)
    leads: list[Source] = []
    for campus, query in discovery_queries():
        if spend + settings.brave_search_cost_per_request_usd > settings.brave_search_budget_usd:
            break
        for result in search_client.search(query, count=min(limit, 20)):
            try:
                title = result.get("title", "")
                leads.append(Source(url=normalize_url(result["url"]), title=title, discovered_at=timestamp,
                                    campus=campus, priority=sum(word in title.casefold() for word in
                                    ("deals", "specials", "happy hour", "promotions", "offers"))))
            except (KeyError, ValueError):
                continue
        spend += settings.brave_search_cost_per_request_usd
    _save_ledger(settings, {"search_spend_usd": spend, "last_discovery_at": timestamp.isoformat()})
    sources = deduplicate_sources(known_sources(settings) + leads)
    _save_sources(settings, sources)
    return sorted(deduplicate_sources(leads), key=lambda source: source.priority, reverse=True)[:limit]
