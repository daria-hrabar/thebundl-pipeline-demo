"""Shared AI extraction contract."""

from abc import ABC, abstractmethod

from thebundl.schemas import DealCandidate


class AIExtractor(ABC):
    # Adapters may expose cumulative `rejections` records containing stage,
    # source_url, candidate, accepted=False, fixed reasons and reason_codes.
    # The runner snapshots their length and retains new records even on failure.
    @abstractmethod
    def extract(self, text: str, source_url: str) -> list[DealCandidate]:
        """Extract candidates from untrusted HTML text with no external tools."""
