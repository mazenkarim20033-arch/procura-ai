from app.ai.providers.base import LLMProvider
from app.ai.providers.mock import MockProvider
from app.ai.providers.openai_compat import OpenAICompatProvider
from app.config import Settings, get_settings
from app.errors import DomainError

GROQ_URL = "https://api.groq.com/openai/v1"


class ProviderNotConfigured(DomainError):
    status_code = 503
    code = "llm_not_configured"


def build_provider(settings: Settings | None = None) -> LLMProvider:
    s = settings or get_settings()
    if s.llm_provider == "mock":
        return MockProvider()
    if s.llm_provider in {"groq", "openai_compat"}:
        base = s.llm_base_url or (GROQ_URL if s.llm_provider == "groq" else None)
        missing = [n for n, v in (("LLM_API_KEY", s.llm_api_key), ("LLM_MODEL", s.llm_model), ("LLM_BASE_URL", base))
                   if not v]
        if missing:
            raise ProviderNotConfigured(f"LLM provider '{s.llm_provider}' needs: {', '.join(missing)}")
        return OpenAICompatProvider(base_url=base, api_key=s.llm_api_key, model=s.llm_model, name=s.llm_provider)
    raise ProviderNotConfigured(f"Unknown LLM_PROVIDER '{s.llm_provider}'")


def estimate_cost(settings: Settings, input_tokens: int | None, output_tokens: int | None) -> float | None:
    """USD estimate from token counts, only when both prices are configured; otherwise unknown (None)."""
    if None in (settings.llm_price_in_per_m, settings.llm_price_out_per_m, input_tokens, output_tokens):
        return None
    return round(input_tokens * settings.llm_price_in_per_m / 1e6 + output_tokens * settings.llm_price_out_per_m / 1e6, 6)
