"""AI extractors."""

from .base import AIExtractor
from .groq_provider import GroqExtractor


def build_extractor(settings: object) -> AIExtractor:
    """Select exactly the configured provider; never fall back to another one."""
    if getattr(settings, "ai_provider") != "groq":
        raise ValueError(f"Unsupported AI_PROVIDER: {getattr(settings, 'ai_provider')}")
    api_key = getattr(settings, "groq_api_key")
    if api_key is None:
        raise ValueError("GROQ_API_KEY is required when AI_PROVIDER=groq")
    return GroqExtractor(api_key.get_secret_value(), model=getattr(settings, "ai_model"))

__all__ = ["AIExtractor", "GroqExtractor", "build_extractor"]
