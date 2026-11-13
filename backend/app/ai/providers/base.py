"""LLM provider interface. Providers return schema-validated objects plus usage/latency so every call
can be logged (llm_calls) and costed. The AI never receives tools and never writes state."""
from dataclasses import dataclass
from typing import Generic, Protocol, TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class LLMError(Exception):
    """Provider failure after retries (network, rate limit, or persistently invalid output)."""


@dataclass
class LLMResult(Generic[T]):
    parsed: T
    provider: str
    model: str
    input_tokens: int | None
    output_tokens: int | None
    latency_ms: int
    retries: int
    is_mock: bool
    raw: str = ""


class LLMProvider(Protocol):
    name: str
    model: str
    is_mock: bool

    def generate(
        self, *, system: str, user: str, schema: type[T], prompt_name: str, prompt_version: str,
    ) -> LLMResult[T]: ...
