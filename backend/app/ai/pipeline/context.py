"""Pure data the assessment pipeline works on. It is built from the database in production and from
scenario files in the benchmark, so the core logic never touches SQL."""
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Protocol

from app.rules.intake import RequestSnapshot


@dataclass(frozen=True)
class Clause:
    ref: str  # "PRC-002:1.3"
    policy_code: str
    number: str
    text: str
    chunk_id: str | None = None  # database chunk id (None for in-memory corpora)
    section_path: str | None = None


@dataclass
class ClauseHit:
    clause: Clause
    similarity: float


class PolicyCorpus(Protocol):
    def get(self, ref: str) -> Clause | None:
        """Exact clause lookup (None if that policy/clause is not loaded or not in force)."""
        ...

    def search(self, query: str, k: int) -> list[ClauseHit]:
        """Semantic retrieval over all loaded clauses."""
        ...


@dataclass
class QuoteCtx:
    document_id: str
    filename: str
    vendor_name: str | None
    currency: str | None
    total: Decimal | None
    issue_date: date | None
    valid_until: date | None
    payment_terms: str | None = None
    issue_codes: list[str] = field(default_factory=list)  # extraction validation codes, e.g. "total_mismatch"


@dataclass
class ContractCtx:
    document_id: str
    filename: str
    vendor_name: str | None
    currency: str | None
    total_value: Decimal | None
    payment_terms: str | None = None


@dataclass
class AssessmentContext:
    request: RequestSnapshot
    quotes: list[QuoteCtx] = field(default_factory=list)
    contracts: list[ContractCtx] = field(default_factory=list)
    approved_suppliers: list[str] | None = None  # None = no approved-supplier list configured
    intake: dict = field(default_factory=dict)  # output of services.requests.run_intake
    untrusted_text: list[tuple[str, str | None]] = field(default_factory=list)  # (source, text) for the injection scan
