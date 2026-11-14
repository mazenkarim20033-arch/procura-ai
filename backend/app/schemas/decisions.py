from typing import Literal
from uuid import UUID

from pydantic import Field

from app.schemas.documents import Strict


class FindingReviewIn(Strict):
    finding_id: UUID
    verdict: Literal["agree", "disagree", "unsure"]
    note: str | None = Field(default=None, max_length=2000)


class DecisionIn(Strict):
    action: Literal["approve", "reject", "request_info"]
    reasoning: str = Field(max_length=5000)
    assessment_id: UUID | None = None  # required for approve/reject: the assessment the reviewer actually looked at
    finding_reviews: list[FindingReviewIn] = Field(default_factory=list, max_length=100)


class InfoResponseIn(Strict):
    message: str = Field(min_length=3, max_length=2000)
