"""Future Brave Search source discovery adapter."""

from __future__ import annotations

from .config import Settings
from .schemas import Source


def discover_sources(settings: Settings, limit: int) -> list[Source]:
    """Discover and rank reusable local-deal pages (not yet implemented)."""
    del settings, limit
    return []
