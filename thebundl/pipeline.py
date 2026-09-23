"""Orchestration and local run-artifact support."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from .config import Settings
from .collection import CollectionResult, collect_sources
from .discovery import SearchClient, discover_sources, discovery_due, known_sources

if TYPE_CHECKING:
    import httpx


def write_run_artifact(settings: Settings, command: str, *, limit: int | None, publish: bool) -> Path:
    """Persist an honest record of a skeleton command under ignored work/."""
    settings.work_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(UTC)
    path = settings.work_dir / f"{timestamp:%Y%m%dT%H%M%SZ}-{command}.json"
    path.write_text(json.dumps({
        "timestamp": timestamp.isoformat(), "command": command, "limit": limit,
        "publish_requested": publish, "status": "not_implemented",
        "message": "No sources, deals, or Supabase writes were produced.",
    }, indent=2) + "\n", encoding="utf-8")
    return path


def weekly_report(settings: Settings, days: int) -> Path:
    """Write an actual-count report without inventing deals."""
    path = write_run_artifact(settings, "report", limit=None, publish=False)
    payload = json.loads(path.read_text(encoding="utf-8"))
    payload.update({"days": days, "distinct_new_deals": 0, "target_distinct_new_deals_per_week": 10})
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def collect_daily_sources(settings: Settings, *, client: "httpx.Client", limit: int,
                          search_client: SearchClient | None = None) -> list[CollectionResult]:
    """Discover only when due, then reuse all known sources for HTML collection.

    This stops before AI extraction and publishing; callers decide those later
    after validation and duplicate checks.
    """
    if discovery_due(settings):
        discover_sources(settings, limit, search_client=search_client)
    return collect_sources(known_sources(settings)[:limit], client=client,
                           pace_seconds=settings.domain_pacing_seconds)
