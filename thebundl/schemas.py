"""Typed records passed between pipeline stages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, HttpUrl


class Source(BaseModel):
    url: HttpUrl
    title: str
    discovered_at: datetime
    campus: str
    priority: int = 0
    last_collected_at: datetime | None = None
    content_hash: str | None = None


class ExtractedPage(BaseModel):
    source_url: HttpUrl
    text: str
    links: list[HttpUrl] = []
    structured_data: list[dict[str, Any]] = []


class ExtractedDeal(BaseModel):
    """Strict, intermediate model output. It has no pipeline-owned fields."""

    model_config = ConfigDict(extra="forbid")

    business_name: str
    address: str
    title: str
    description: str
    evidence_text: str
    restrictions: str | None


class ExtractionPayload(BaseModel):
    """The strict structured response requested from the AI provider."""

    model_config = ConfigDict(extra="forbid")

    deals: list[ExtractedDeal]


class DealCandidate(BaseModel):
    """Candidate mapped to the existing deals-table columns before insertion."""

    business_name: str
    address: str
    campus: Literal["baruch", "columbia"] | None = None
    title: str
    description: str
    source_url: HttpUrl
    evidence_text: str
    restrictions: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    fingerprint: str | None = None


class ValidationResult(BaseModel):
    candidate: DealCandidate
    accepted: bool
    reasons: list[str] = []
    branch_evidence_urls: list[str] = []
