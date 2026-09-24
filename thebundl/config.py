"""Configuration for thebundl. Secrets are loaded but never displayed."""

from __future__ import annotations

from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Campus(BaseModel):
    """A verified campus centre coordinate in WGS84 decimal degrees."""

    name: str
    latitude: float
    longitude: float
    radius_miles: float = Field(default=2.0, gt=0)


# Coordinates verified against the institutions' official campus addresses.
BARUCH_COLLEGE = Campus(
    name="Baruch College main campus", latitude=40.7406, longitude=-73.9832
)
COLUMBIA_UNIVERSITY = Campus(
    name="Columbia University Morningside campus", latitude=40.8075, longitude=-73.9626
)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    brave_search_api_key: SecretStr | None = None
    groq_api_key: SecretStr | None = None
    supabase_url: str | None = None
    supabase_key: SecretStr | None = None
    ai_provider: str = "groq"
    ai_model: str = "openai/gpt-oss-20b"
    discovery_interval_days: int = Field(default=14, ge=14)
    collection_interval_hours: int = Field(default=24, ge=24)
    brave_search_budget_usd: float = Field(default=5.0, ge=0)
    brave_search_cost_per_request_usd: float = Field(default=0.0, ge=0)
    max_search_requests_per_run: int = Field(default=12, ge=0)
    max_ai_requests_per_run: int = Field(default=24, ge=0)
    ai_budget_usd: float = Field(default=1.0, ge=0)
    ai_cost_per_request_usd: float = Field(default=0.05, gt=0)
    max_sources_per_run: int = Field(default=20, ge=1)
    http_timeout_seconds: float = Field(default=15.0, gt=0)
    domain_pacing_seconds: float = Field(default=1.0, ge=0)
    source_cooldown_days: int = Field(default=14, ge=1)
    branch_cache_days: int = Field(default=30, ge=1)
    work_dir: Path = Path("work")
    campuses: tuple[Campus, Campus] = (BARUCH_COLLEGE, COLUMBIA_UNIVERSITY)


def get_settings() -> Settings:
    """Load local environment configuration without exposing credentials."""
    load_dotenv()
    return Settings()


def configuration_status(settings: Settings, *, publish: bool = False) -> dict[str, bool]:
    """Return key-presence only; values must never be logged."""
    return {
        "BRAVE_SEARCH_API_KEY": settings.brave_search_api_key is not None,
        "GROQ_API_KEY": (
            settings.groq_api_key is not None if settings.ai_provider == "groq" else False
        ),
        "SUPABASE_URL": settings.supabase_url is not None,
        "SUPABASE_KEY": settings.supabase_key is not None,
        "publish_ready": (not publish)
        or (settings.supabase_url is not None and settings.supabase_key is not None),
    }
