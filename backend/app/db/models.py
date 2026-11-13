"""SQLAlchemy models. Source of truth for the schema; see docs/ARCHITECTURE.md section 3.

AI assessments (assessments/findings/...) and human decisions (decisions/...) live in
separate tables on purpose: a decision never mutates an assessment and vice versa.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from enum import Enum as PyEnum

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Computed,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.db import enums as E

EMBEDDING_DIM = 384

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)


def enum_col(enum_cls: type[PyEnum], name: str) -> Enum:
    """Portable string enum with a CHECK constraint (no native PG enum, easy to migrate)."""
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        create_constraint=True,
        length=32,
        values_callable=lambda e: [m.value for m in e],
    )


def pk() -> Mapped[uuid.UUID]:
    return mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4,
        server_default=text("gen_random_uuid()"),
    )


def fk(target: str, nullable: bool = False, ondelete: str | None = None):
    return mapped_column(UUID(as_uuid=True), ForeignKey(target, ondelete=ondelete), nullable=nullable)


def created() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def money(precision: int = 14, scale: int = 2):
    return mapped_column(Numeric(precision, scale), nullable=True)


# ---------------------------------------------------------------- identity & config
class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = pk()
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    role: Mapped[E.Role] = mapped_column(enum_col(E.Role, "role"))
    department: Mapped[str | None] = mapped_column(String(120))
    created_at: Mapped[datetime] = created()


class AppSetting(Base):
    __tablename__ = "app_settings"
    key: Mapped[str] = mapped_column(String(120), primary_key=True)
    value_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    updated_at: Mapped[datetime] = created()


# ---------------------------------------------------------------- documents & retrieval
class Document(Base):
    __tablename__ = "documents"
    id: Mapped[uuid.UUID] = pk()
    filename: Mapped[str] = mapped_column(String(512))
    sha256: Mapped[str] = mapped_column(String(64), unique=True)
    mime: Mapped[str] = mapped_column(String(120))
    doc_type: Mapped[E.DocType] = mapped_column(enum_col(E.DocType, "doc_type"), default=E.DocType.other)
    doc_type_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))
    language: Mapped[str | None] = mapped_column(String(8))
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    status: Mapped[E.DocStatus] = mapped_column(enum_col(E.DocStatus, "doc_status"), default=E.DocStatus.uploaded)
    ocr_used: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    page_count: Mapped[int | None] = mapped_column(Integer)
    storage_path: Mapped[str | None] = mapped_column(String(1024))
    uploaded_by: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


class DocumentPage(Base):
    __tablename__ = "document_pages"
    __table_args__ = (UniqueConstraint("document_id", "page_no"),)
    id: Mapped[uuid.UUID] = pk()
    document_id: Mapped[uuid.UUID] = fk("documents.id", ondelete="CASCADE")
    page_no: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    ocr_confidence: Mapped[Decimal | None] = mapped_column(Numeric(4, 3))


class Extraction(Base):
    __tablename__ = "extractions"
    id: Mapped[uuid.UUID] = pk()
    document_id: Mapped[uuid.UUID] = fk("documents.id", ondelete="CASCADE")
    schema_name: Mapped[str] = mapped_column(String(80))
    schema_version: Mapped[str] = mapped_column(String(20))
    data_json: Mapped[dict] = mapped_column(JSONB)
    field_provenance_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    validation_errors_json: Mapped[list] = mapped_column(JSONB, default=list)
    method: Mapped[str] = mapped_column(String(16))  # rules | llm | mock
    prompt_version: Mapped[str | None] = mapped_column(String(80))
    created_at: Mapped[datetime] = created()
    __table_args__ = (CheckConstraint("method in ('rules','llm','mock')", name="method"),)


class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = (UniqueConstraint("code", "version"),)
    id: Mapped[uuid.UUID] = pk()
    code: Mapped[str] = mapped_column(String(40))
    title: Mapped[str] = mapped_column(String(255))
    version: Mapped[str] = mapped_column(String(20))
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    category: Mapped[str | None] = mapped_column(String(80))
    document_id: Mapped[uuid.UUID | None] = fk("documents.id", nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="active")
    created_at: Mapped[datetime] = created()


class Chunk(Base):
    __tablename__ = "chunks"
    id: Mapped[uuid.UUID] = pk()
    document_id: Mapped[uuid.UUID] = fk("documents.id", ondelete="CASCADE")
    policy_id: Mapped[uuid.UUID | None] = fk("policies.id", nullable=True, ondelete="CASCADE")
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    section_path: Mapped[str | None] = mapped_column(String(512))
    text: Mapped[str] = mapped_column(Text)
    char_start: Mapped[int | None] = mapped_column(Integer)
    char_end: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    metadata_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(120))
    tsv = mapped_column(TSVECTOR, Computed("to_tsvector('english', text)", persisted=True))
    __table_args__ = (
        Index("ix_chunks_tsv", "tsv", postgresql_using="gin"),
        Index(
            "ix_chunks_embedding_hnsw", "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
        Index("ix_chunks_policy_id", "policy_id"),
        Index("ix_chunks_document_id", "document_id"),
    )


class PolicyRule(Base):
    __tablename__ = "policy_rules"
    id: Mapped[uuid.UUID] = pk()
    policy_id: Mapped[uuid.UUID] = fk("policies.id", ondelete="CASCADE")
    rule_code: Mapped[str] = mapped_column(String(60), unique=True)
    description: Mapped[str] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    params_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    source_chunk_id: Mapped[uuid.UUID | None] = fk("chunks.id", nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=text("true"))


# ---------------------------------------------------------------- vendors
class Vendor(Base):
    __tablename__ = "vendors"
    id: Mapped[uuid.UUID] = pk()
    canonical_name: Mapped[str] = mapped_column(String(255))
    normalized_name: Mapped[str] = mapped_column(String(255), unique=True)
    country: Mapped[str | None] = mapped_column(String(80))
    tax_id: Mapped[str | None] = mapped_column(String(60))
    contact_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    first_seen_doc_id: Mapped[uuid.UUID | None] = fk("documents.id", nullable=True)
    created_at: Mapped[datetime] = created()


class VendorAlias(Base):
    __tablename__ = "vendor_aliases"
    __table_args__ = (UniqueConstraint("vendor_id", "alias"),)
    id: Mapped[uuid.UUID] = pk()
    vendor_id: Mapped[uuid.UUID] = fk("vendors.id", ondelete="CASCADE")
    alias: Mapped[str] = mapped_column(String(255))
    source_doc_id: Mapped[uuid.UUID | None] = fk("documents.id", nullable=True)


# ---------------------------------------------------------------- purchase requests
class PurchaseRequest(Base):
    __tablename__ = "purchase_requests"
    id: Mapped[uuid.UUID] = pk()
    request_no: Mapped[str] = mapped_column(String(40), unique=True)
    requester_id: Mapped[uuid.UUID | None] = fk("users.id", nullable=True)
    requester_name: Mapped[str | None] = mapped_column(String(255))  # as written; users table is demo-only
    department: Mapped[str | None] = mapped_column(String(120))
    currency: Mapped[str | None] = mapped_column(String(3))
    total_amount = money()
    supplier_id: Mapped[uuid.UUID | None] = fk("vendors.id", nullable=True)  # resolved by vendor intelligence
    supplier_name: Mapped[str | None] = mapped_column(String(255))  # as written on the request
    source_document_id: Mapped[uuid.UUID | None] = fk("documents.id", nullable=True)
    justification: Mapped[str | None] = mapped_column(Text)
    category: Mapped[str | None] = mapped_column(String(80))
    status: Mapped[E.RequestStatus] = mapped_column(
        enum_col(E.RequestStatus, "request_status"), default=E.RequestStatus.submitted
    )
    is_synthetic: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    submitted_at: Mapped[datetime] = created()
    fingerprint: Mapped[str | None] = mapped_column(String(64))
    __table_args__ = (
        Index("ix_purchase_requests_status", "status"),
        Index("ix_purchase_requests_fingerprint", "fingerprint"),
    )


class RequestItem(Base):
    __tablename__ = "request_items"
    id: Mapped[uuid.UUID] = pk()
    request_id: Mapped[uuid.UUID] = fk("purchase_requests.id", ondelete="CASCADE")
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_cost = mapped_column(Numeric(14, 4), nullable=True)
    line_total = money()
    category: Mapped[str | None] = mapped_column(String(80))
    item_embedding = mapped_column(Vector(EMBEDDING_DIM), nullable=True)


class RequestDocument(Base):
    __tablename__ = "request_documents"
    request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("purchase_requests.id", ondelete="CASCADE"), primary_key=True
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("documents.id", ondelete="CASCADE"), primary_key=True
    )
    role: Mapped[str | None] = mapped_column(String(40))


class Quotation(Base):
    __tablename__ = "quotations"
    id: Mapped[uuid.UUID] = pk()
    vendor_id: Mapped[uuid.UUID | None] = fk("vendors.id", nullable=True)
    request_id: Mapped[uuid.UUID | None] = fk("purchase_requests.id", nullable=True, ondelete="SET NULL")
    document_id: Mapped[uuid.UUID | None] = fk("documents.id", nullable=True)
    quote_no: Mapped[str | None] = mapped_column(String(60))
    issue_date: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    currency: Mapped[str | None] = mapped_column(String(3))
    subtotal = money()
    tax = money()
    total = money()
    payment_terms: Mapped[str | None] = mapped_column(String(255))
    delivery_days: Mapped[int | None] = mapped_column(Integer)


class QuotationItem(Base):
    __tablename__ = "quotation_items"
    id: Mapped[uuid.UUID] = pk()
    quotation_id: Mapped[uuid.UUID] = fk("quotations.id", ondelete="CASCADE")
    description: Mapped[str] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(12, 3))
    unit_price = mapped_column(Numeric(14, 4), nullable=True)
    line_total = money()
    request_item_id: Mapped[uuid.UUID | None] = fk("request_items.id", nullable=True, ondelete="SET NULL")


# ---------------------------------------------------------------- AI assessments (append-only)
class Assessment(Base):
    __tablename__ = "assessments"
    __table_args__ = (UniqueConstraint("request_id", "version"),)
    id: Mapped[uuid.UUID] = pk()
    request_id: Mapped[uuid.UUID] = fk("purchase_requests.id", ondelete="CASCADE")
    version: Mapped[int] = mapped_column(Integer)
    overall_risk: Mapped[E.RiskLevel] = mapped_column(enum_col(E.RiskLevel, "risk_level"))
    compliance_status: Mapped[E.ComplianceStatus] = mapped_column(
        enum_col(E.ComplianceStatus, "compliance_status")
    )
    confidence = mapped_column(Numeric(4, 3), nullable=True)
    summary: Mapped[str | None] = mapped_column(Text)
    financial_risks_json: Mapped[list] = mapped_column(JSONB, default=list)
    next_steps_json: Mapped[list] = mapped_column(JSONB, default=list)
    missing_info_json: Mapped[list] = mapped_column(JSONB, default=list)
    provider: Mapped[str | None] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_versions_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    is_mock: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    est_cost_usd = mapped_column(Numeric(10, 6), nullable=True)
    created_at: Mapped[datetime] = created()


class Finding(Base):
    __tablename__ = "findings"
    id: Mapped[uuid.UUID] = pk()
    assessment_id: Mapped[uuid.UUID] = fk("assessments.id", ondelete="CASCADE")
    category: Mapped[E.FindingCategory] = mapped_column(enum_col(E.FindingCategory, "finding_category"))
    source: Mapped[E.FindingSource] = mapped_column(enum_col(E.FindingSource, "finding_source"))
    rule_code: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(255))
    explanation: Mapped[str] = mapped_column(Text)
    confidence = mapped_column(Numeric(4, 3), nullable=True)
    severity: Mapped[E.RiskLevel | None] = mapped_column(enum_col(E.RiskLevel, "finding_severity"), nullable=True)
    __table_args__ = (
        # Only deterministic rules may emit a confirmed violation (PRD FR-D).
        CheckConstraint("category <> 'confirmed_violation' or source = 'rule'", name="confirmed_needs_rule"),
    )


class FindingEvidence(Base):
    __tablename__ = "finding_evidence"
    id: Mapped[uuid.UUID] = pk()
    finding_id: Mapped[uuid.UUID] = fk("findings.id", ondelete="CASCADE")
    kind: Mapped[E.EvidenceKind] = mapped_column(enum_col(E.EvidenceKind, "evidence_kind"))
    chunk_id: Mapped[uuid.UUID | None] = fk("chunks.id", nullable=True)
    quote: Mapped[str | None] = mapped_column(Text)
    ref_json: Mapped[dict] = mapped_column(JSONB, default=dict)


class RetrievalLog(Base):
    __tablename__ = "retrieval_logs"
    id: Mapped[uuid.UUID] = pk()
    assessment_id: Mapped[uuid.UUID | None] = fk("assessments.id", nullable=True, ondelete="CASCADE")
    query: Mapped[str] = mapped_column(Text)
    filters_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    results_json: Mapped[list] = mapped_column(JSONB, default=list)
    reranked: Mapped[bool] = mapped_column(Boolean, default=False, server_default=text("false"))
    created_at: Mapped[datetime] = created()


class LlmCall(Base):
    __tablename__ = "llm_calls"
    id: Mapped[uuid.UUID] = pk()
    assessment_id: Mapped[uuid.UUID | None] = fk("assessments.id", nullable=True, ondelete="SET NULL")
    purpose: Mapped[str] = mapped_column(String(60))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(120))
    prompt_name: Mapped[str | None] = mapped_column(String(80))
    prompt_version: Mapped[str | None] = mapped_column(String(40))
    input_tokens: Mapped[int | None] = mapped_column(Integer)
    output_tokens: Mapped[int | None] = mapped_column(Integer)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    est_cost_usd = mapped_column(Numeric(10, 6), nullable=True)
    retries: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    status: Mapped[str] = mapped_column(String(16))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()


# ---------------------------------------------------------------- human decisions
class Decision(Base):
    __tablename__ = "decisions"
    id: Mapped[uuid.UUID] = pk()
    request_id: Mapped[uuid.UUID] = fk("purchase_requests.id", ondelete="CASCADE")
    assessment_id: Mapped[uuid.UUID | None] = fk("assessments.id", nullable=True)
    reviewer_id: Mapped[uuid.UUID] = fk("users.id")
    action: Mapped[E.DecisionAction] = mapped_column(enum_col(E.DecisionAction, "decision_action"))
    reasoning: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    __table_args__ = (CheckConstraint("length(btrim(reasoning)) > 0", name="reasoning_required"),)


class FindingReview(Base):
    __tablename__ = "finding_reviews"
    id: Mapped[uuid.UUID] = pk()
    decision_id: Mapped[uuid.UUID] = fk("decisions.id", ondelete="CASCADE")
    finding_id: Mapped[uuid.UUID] = fk("findings.id")
    verdict: Mapped[E.Verdict] = mapped_column(enum_col(E.Verdict, "verdict"))
    note: Mapped[str | None] = mapped_column(Text)


class InfoRequest(Base):
    __tablename__ = "info_requests"
    id: Mapped[uuid.UUID] = pk()
    request_id: Mapped[uuid.UUID] = fk("purchase_requests.id", ondelete="CASCADE")
    decision_id: Mapped[uuid.UUID | None] = fk("decisions.id", nullable=True)
    message: Mapped[str] = mapped_column(Text)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = created()


# ---------------------------------------------------------------- audit, jobs, eval
class AuditLog(Base):
    """Insert-only, hash-chained (tamper-evident, not tamper-proof). See services/audit.py."""

    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    actor_type: Mapped[str] = mapped_column(String(16))  # user | system | ai
    actor_id: Mapped[str | None] = mapped_column(String(64))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(60))
    entity_id: Mapped[str | None] = mapped_column(String(64))
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
    __table_args__ = (
        CheckConstraint("actor_type in ('user','system','ai')", name="actor_type"),
        Index("ix_audit_log_entity", "entity_type", "entity_id"),
    )


class Job(Base):
    __tablename__ = "jobs"
    id: Mapped[uuid.UUID] = pk()
    kind: Mapped[str] = mapped_column(String(60))
    payload_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    status: Mapped[str] = mapped_column(String(16), default="queued")
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default=text("0"))
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = created()
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        CheckConstraint("status in ('queued','running','done','failed')", name="status"),
        Index("ix_jobs_status_created", "status", "created_at"),
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"
    id: Mapped[uuid.UUID] = pk()
    git_sha: Mapped[str | None] = mapped_column(String(40))
    config_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    metrics_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    started_at: Mapped[datetime] = created()


class EvalCaseResult(Base):
    __tablename__ = "eval_case_results"
    id: Mapped[uuid.UUID] = pk()
    run_id: Mapped[uuid.UUID] = fk("eval_runs.id", ondelete="CASCADE")
    case_id: Mapped[str] = mapped_column(String(80))
    suite: Mapped[str] = mapped_column(String(40))
    expected_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    actual_json: Mapped[dict] = mapped_column(JSONB, default=dict)
    passed: Mapped[bool] = mapped_column(Boolean)
