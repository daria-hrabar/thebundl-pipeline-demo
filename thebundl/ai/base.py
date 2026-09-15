"""Shared AI extraction contract."""

from abc import ABC, abstractmethod

from thebundl.schemas import DealCandidate


class AIExtractor(ABC):
    @abstractmethod
    def extract(self, text: str, source_url: str) -> list[DealCandidate]:
        """Extract candidates from untrusted HTML text with no external tools."""
