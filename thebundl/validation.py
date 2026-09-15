"""Pipeline-owned candidate checks and fields."""

from __future__ import annotations

import hashlib
import math

from .config import Campus
from .schemas import DealCandidate, ValidationResult


def campus_for_location(latitude: float, longitude: float, campuses: tuple[Campus, ...]) -> str | None:
    """Assign a campus only from a previously verified branch coordinate."""
    for key, campus in (("baruch", campuses[0]), ("columbia", campuses[1])):
        if _distance_miles(latitude, longitude, campus.latitude, campus.longitude) <= campus.radius_miles:
            return key
    return None


def fingerprint_for(candidate: DealCandidate) -> str:
    """Stable ID based on branch and offer facts, never a collection date."""
    values = (candidate.business_name, candidate.address, candidate.title,
              candidate.description, candidate.restrictions or "")
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


def _distance_miles(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 3958.7613
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi, delta_lambda = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    return radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
