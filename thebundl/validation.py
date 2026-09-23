"""Pipeline-owned candidate checks and fields."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from .config import Campus
from .schemas import DealCandidate, ExtractedPage, ValidationResult

_PROMOTION_WORDS = ("off", "deal", "special", "happy hour", "promotion", "offer", "discount", "free", "bogo")
_PERIOD_RE = re.compile(r"\b(?:valid\s+)?(?:through|until|from)\s+[^.\n;]{1,80}", re.IGNORECASE)


@dataclass(frozen=True)
class GeocodeMatch:
    """A cached geocoder result, never a coordinate supplied by the AI."""

    address: str
    latitude: float
    longitude: float


class Geocoder(Protocol):
    def lookup(self, address: str) -> list[GeocodeMatch]: ...


class CachedGeocoder:
    """File-backed cache around a rate-limited geocoder adapter."""

    def __init__(self, upstream: Geocoder, path: Path) -> None:
        self.upstream = upstream
        self.path = path

    def lookup(self, address: str) -> list[GeocodeMatch]:
        cache = json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {}
        key = " ".join(address.casefold().split())
        if key in cache:
            return [GeocodeMatch(**item) for item in cache[key]]
        matches = self.upstream.lookup(address)
        cache[key] = [match.__dict__ for match in matches]
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(cache, indent=2) + "\n", encoding="utf-8")
        return matches


def campus_for_location(latitude: float, longitude: float, campuses: tuple[Campus, ...]) -> str | None:
    """Assign a campus only from a previously verified branch coordinate."""
    for key, campus in (("baruch", campuses[0]), ("columbia", campuses[1])):
        if _distance_miles(latitude, longitude, campus.latitude, campus.longitude) <= campus.radius_miles:
            return key
    return None


def fingerprint_for(candidate: DealCandidate) -> str:
    """Stable ID based on branch and offer facts, never a collection date."""
    period = " ".join(_PERIOD_RE.findall(f"{candidate.description} {candidate.evidence_text}"))
    # This deliberately omits collection date and AI metadata.  An offer's
    # branch, offer wording, restrictions, and explicitly stated period define
    # the exact duplicate guard.
    values = (candidate.business_name, candidate.address, candidate.title,
              candidate.restrictions or "", period)
    normalised = "|".join(" ".join(value.casefold().split()) for value in values)
    return hashlib.sha256(normalised.encode("utf-8")).hexdigest()


def prepare_for_insertion(candidate: DealCandidate, *, latitude: float, longitude: float,
                          campuses: tuple[Campus, ...]) -> ValidationResult:
    """Add campus and fingerprint after an upstream resolver verifies coordinates."""
    campus = campus_for_location(latitude, longitude, campuses)
    if campus is None:
        return ValidationResult(candidate=candidate, accepted=False,
                                reasons=["verified branch is outside campus coverage"])
    prepared = candidate.model_copy(update={"campus": campus})
    return ValidationResult(candidate=prepared.model_copy(update={"fingerprint": fingerprint_for(prepared)}),
                            accepted=True)


def validate_candidate(candidate: DealCandidate, page: ExtractedPage, *, geocoder: Geocoder,
                       campuses: tuple[Campus, ...]) -> ValidationResult:
    """Accept only source-evidenced, promotional, uniquely resolved branches."""
    content = " ".join(page.text.split())
    evidence = " ".join(candidate.evidence_text.split())
    reasons: list[str] = []
    if not evidence or evidence not in content:
        reasons.append("evidence excerpt is absent from collected content")
    if " ".join(candidate.address.split()) not in content:
        reasons.append("branch address is not source-backed")
    offer_text = f"{candidate.title} {candidate.description} {candidate.evidence_text}".casefold()
    if not any(marker in offer_text for marker in _PROMOTION_WORDS):
        reasons.append("regular menu item is not an explicit promotion")
    material_prices = re.findall(r"\$\s*\d+(?:\.\d{2})?", f"{candidate.title} {candidate.description}")
    if any(price not in evidence for price in material_prices):
        reasons.append("material price is not supported by the evidence excerpt")
    for value, label in ((candidate.restrictions, "restriction"),):
        if value and " ".join(value.split()) not in evidence:
            reasons.append(f"{label} is absent from the evidence excerpt")
    if reasons:
        return ValidationResult(candidate=candidate, accepted=False, reasons=reasons)
    matches = geocoder.lookup(candidate.address)
    if len(matches) != 1:
        return ValidationResult(candidate=candidate, accepted=False,
                                reasons=["branch address could not be resolved unambiguously"])
    return prepare_for_insertion(candidate, latitude=matches[0].latitude, longitude=matches[0].longitude,
                                 campuses=campuses)


def _distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi, delta_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
