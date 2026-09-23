"""Source and candidate deduplication primitives."""

from .schemas import DealCandidate, Source
from .validation import fingerprint_for


def deduplicate_sources(sources: list[Source]) -> list[Source]:
    """Keep one reusable source per canonical URL."""
    unique: dict[str, Source] = {}
    for source in sources:
        unique.setdefault(str(source.url).rstrip("/"), source)
    return list(unique.values())


def exact_duplicate(candidate: DealCandidate, existing: list[DealCandidate]) -> bool:
    """Exact local guard; the database unique constraint remains authoritative."""
    fingerprint = fingerprint_for(candidate)
    return any((deal.fingerprint or fingerprint_for(deal)) == fingerprint for deal in existing)


def similar_same_branch(candidate: DealCandidate, existing: list[DealCandidate]) -> list[DealCandidate]:
    """Return same-branch near matches for an optional AI rewording decision."""
    branch = _normalise(candidate.business_name), _normalise(candidate.address)
    words = set(_normalise(candidate.title).split())
    return [deal for deal in existing
            if (_normalise(deal.business_name), _normalise(deal.address)) == branch
            and words.intersection(_normalise(deal.title).split())]


def _normalise(value: str) -> str:
    return " ".join(value.casefold().split())
