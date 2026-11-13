from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class LLMFinding(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str = Field(min_length=3, max_length=200)
    explanation: str = Field(min_length=3, max_length=2000)
    clause_ref: str  # must be one of the provided clauses; checked by the verifier, not trusted
    quote: str = Field(min_length=3, max_length=1000)
    confidence: float = Field(ge=0, le=1)
    # No "confirmed_violation": only deterministic rules may emit that.
    category: Literal["potential_violation", "inconclusive", "compliant"]


class ClauseFindings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    findings: list[LLMFinding] = Field(default_factory=list, max_length=20)
