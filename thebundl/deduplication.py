"""Source and candidate deduplication primitives."""

from .schemas import Source


def deduplicate_sources(sources: list[Source]) -> list[Source]:
    """Keep one reusable source per canonical URL."""
    unique: dict[str, Source] = {}
    for source in sources:
        unique.setdefault(str(source.url).rstrip("/"), source)
    return list(unique.values())
