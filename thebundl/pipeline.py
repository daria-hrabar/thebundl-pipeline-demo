"""Orchestration and local run-artifact support."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from .config import Settings


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
