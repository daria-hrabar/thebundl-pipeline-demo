"""Supabase persistence boundary for the tables in sql/mock_supabase_tables.sql."""

from __future__ import annotations

from typing import Any

from supabase import create_client

from .config import Settings
from .schemas import DealCandidate, Source
from .observability import request_event, progress


def _client(settings: Settings) -> Any:
    if not settings.supabase_url or settings.supabase_key is None:
        raise RuntimeError("Publishing requires SUPABASE_URL and SUPABASE_KEY for the dedicated test project")
    return create_client(settings.supabase_url, settings.supabase_key.get_secret_value())


def deal_row(candidate: DealCandidate) -> dict[str, str]:
    """Map only to columns that exist in pipeline_deals.

    Schema columns: fingerprint, title, business_name, source_url, evidence.
    Address, campus, model metadata and restrictions are validation inputs and
    deliberately are not written because this test schema has no such columns.
    """
    if not candidate.fingerprint:
        raise ValueError("A validated candidate fingerprint is required before publishing")
    return {
        "fingerprint": candidate.fingerprint,
        "title": candidate.title,
        "business_name": candidate.business_name,
        "source_url": str(candidate.source_url),
        "evidence": candidate.evidence_text,
    }


def existing_fingerprints(settings: Settings, fingerprints: list[str], *, client: Any | None = None) -> set[str]:
    if not fingerprints:
        return set()
    database = client or _client(settings)
    try:
        with request_event("Supabase duplicate lookup"):
            response = database.table("pipeline_deals").select("fingerprint").in_("fingerprint", fingerprints).execute()
        return {row["fingerprint"] for row in (response.data or [])}
    except Exception as error:
        raise RuntimeError(f"Could not check duplicate deals in Supabase: {error.__class__.__name__}") from error


def publish_candidates(settings: Settings, candidates: list[DealCandidate], *, client: Any | None = None) -> int:
    """Insert validated non-duplicates into pipeline_deals in the test project."""
    rows = list({candidate.fingerprint: deal_row(candidate) for candidate in candidates}.values())
    if not rows:
        return 0
    database = client or _client(settings)
    existing = existing_fingerprints(settings, [row["fingerprint"] for row in rows], client=database)
    rows = [row for row in rows if row["fingerprint"] not in existing]
    if not rows:
        return 0
    try:
        with request_event("Supabase pipeline_deals insert"):
            response = database.table("pipeline_deals").insert(rows).execute()
    except Exception as error:
        raise RuntimeError(f"Could not publish deals to Supabase: {error.__class__.__name__}") from error
    if response.data is None or len(response.data) != len(rows):
        raise RuntimeError("Supabase did not confirm inserted rows; verify publication before retrying")
    progress(f"Saved {len(response.data)} deals to Supabase pipeline_deals")
    return len(response.data)


def publish_sources(settings: Settings, sources: list[Source]) -> int:
    """Mirror validated deal sources after successful extraction/publication only."""
    unique = {str(source.url): source for source in sources}
    rows = [{"canonical_url": str(source.url), "title": source.title,
             "first_seen_at": source.discovered_at.isoformat()}
            for source in unique.values()]
    if not rows:
        return 0
    with request_event("Supabase pipeline_sources insert"):
        response = _client(settings).table("pipeline_sources").upsert(
            rows, on_conflict="canonical_url", ignore_duplicates=True).execute()
    if response.data is None:
        raise RuntimeError("Supabase did not confirm source publication; retry publication")
    progress("Saved source records to Supabase pipeline_sources; staging file retained")
    return len(response.data or [])
