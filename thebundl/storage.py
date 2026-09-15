"""Supabase persistence boundary."""

from .config import Settings
from .schemas import DealCandidate


def publish_candidates(settings: Settings, candidates: list[DealCandidate]) -> int:
    """Publishing to the separate test project is added in a later step."""
    del settings, candidates
    raise NotImplementedError("Supabase publishing is not implemented")
