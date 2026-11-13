"""Database adapters for the assessment pipeline: build the context from stored data, run the pipeline,
persist the immutable result (assessment, findings, evidence, retrieval and LLM logs) and audit it.
Flushes only; the caller commits. The AI result never changes a request to approved/rejected."""
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.pipeline.context import AssessmentContext, ContractCtx, QuoteCtx
from app.ai.pipeline.core import AssessmentResult, assess
from app.ai.pipeline.corpus import DbPolicyCorpus
from app.ai.providers.base import LLMProvider
from app.ai.providers.factory import estimate_cost
from app.config import get_settings
from app.db import enums as E
from app.db.models import (
    AppSetting,
    Assessment,
    Document,
    DocumentPage,
    Extraction,
    Finding,
    FindingEvidence,
    LlmCall,
    PurchaseRequest,
    RequestDocument,
    RetrievalLog,
)
from app.errors import NotFoundError
from app.retrieval.base import Embedder
from app.services import audit
from app.services.requests import _date, _dec, _snapshots, run_intake

APPROVED_KEY = "approved_suppliers"
MAX_SCAN_CHARS = 20000


def get_approved_suppliers(session: Session) -> list[str] | None:
    row = session.get(AppSetting, APPROVED_KEY)
    return None if row is None else list(row.value_json.get("names", []))


def set_approved_suppliers(session: Session, names: list[str], *, actor: str) -> list[str]:
    clean = sorted({n.strip() for n in names if n and n.strip()})
    row = session.get(AppSetting, APPROVED_KEY)
    if row is None:
        session.add(AppSetting(key=APPROVED_KEY, value_json={"names": clean}))
    else:
        row.value_json = {"names": clean}
    audit.append(session, actor_type="user", actor_id=actor, action="settings.approved_suppliers_updated",
                 entity_type="setting", entity_id=APPROVED_KEY, payload={"count": len(clean)})
    session.flush()
    return clean


def _codes(validation_issues: list[dict]) -> list[str]:
    out = []
    for i in validation_issues:
        if i.get("code") in {"missing_field", "invalid_value"}:
            out.append(f"{i['code']}:{i['field']}")
        elif i.get("code") != "parse_warning":
            out.append(i["code"])
    return out


def build_context(session: Session, req: PurchaseRequest) -> AssessmentContext:
    snap, _ = _snapshots(session, req)
    docs = session.execute(
        select(Document).join(RequestDocument, RequestDocument.document_id == Document.id)
        .where(RequestDocument.request_id == req.id)
    ).scalars().all()
    quotes, contracts, untrusted = [], [], []
    for d in docs:
        ex = session.execute(select(Extraction).where(Extraction.document_id == d.id)
                             .order_by(Extraction.created_at.desc())).scalars().first()
        raw = ex.data_json if ex else {}
        if d.doc_type == E.DocType.quotation:
            quotes.append(QuoteCtx(
                str(d.id), d.filename, raw.get("vendor_name"), raw.get("currency"), _dec(raw.get("total")),
                _date(raw.get("issue_date")), _date(raw.get("valid_until")), raw.get("payment_terms"),
                _codes(ex.validation_errors_json) if ex else []))
        elif d.doc_type == E.DocType.contract:
            contracts.append(ContractCtx(str(d.id), d.filename, raw.get("vendor_name"), raw.get("currency"),
                                         _dec(raw.get("total_value")), raw.get("payment_terms")))
        text = "\n".join(p for (p,) in session.execute(
            select(DocumentPage.text).where(DocumentPage.document_id == d.id).order_by(DocumentPage.page_no)))
        untrusted.append((f"document {d.filename}", text[:MAX_SCAN_CHARS]))
    return AssessmentContext(
        request=snap, quotes=quotes, contracts=contracts, approved_suppliers=get_approved_suppliers(session),
        intake=run_intake(session, req.id), untrusted_text=untrusted)


def assess_request(session: Session, request_id: UUID, *, provider: LLMProvider | None, embedder: Embedder,
                   actor: str) -> Assessment:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    settings = get_settings()
    ctx = build_context(session, req)
    corpus = DbPolicyCorpus(session, embedder, req.submitted_at.date() if req.submitted_at else None)
    result = assess(ctx, corpus, provider, min_similarity=settings.relevance_min_similarity)
    return persist_assessment(session, req, result, corpus.retrievals, actor=actor)


def persist_assessment(session: Session, req: PurchaseRequest, result: AssessmentResult, retrievals: list[dict],
                       *, actor: str) -> Assessment:
    settings = get_settings()
    for f in result.findings:  # write-time guard: no evidence, no finding (except inconclusive)
        if f.category != "inconclusive" and not f.evidence:
            raise ValueError(f"finding {f.rule_code} has no evidence")
        for e in f.evidence:
            if e.kind == "policy_chunk" and not e.chunk_id:
                raise ValueError(f"finding {f.rule_code} cites a policy clause without a stored chunk id")
    version = (session.execute(select(func.max(Assessment.version)).where(Assessment.request_id == req.id))
               .scalar() or 0) + 1
    cost = estimate_cost(settings, result.input_tokens, result.output_tokens)
    a = Assessment(
        request_id=req.id, version=version, overall_risk=E.RiskLevel(result.overall_risk),
        compliance_status=E.ComplianceStatus(result.compliance_status), confidence=Decimal(str(result.confidence)),
        summary=result.summary, financial_risks_json=result.financial_risks, next_steps_json=result.next_steps,
        missing_info_json=result.missing_info, provider=result.provider, model=result.model,
        prompt_versions_json=result.prompt_versions, is_mock=result.is_mock, latency_ms=result.latency_ms,
        input_tokens=result.input_tokens, output_tokens=result.output_tokens,
        est_cost_usd=None if cost is None else Decimal(str(cost)),
    )
    session.add(a)
    session.flush()
    for f in result.findings:
        row = Finding(
            assessment_id=a.id, category=E.FindingCategory(f.category), source=E.FindingSource(f.source),
            rule_code=f.rule_code, title=f.title[:255], explanation=f.explanation,
            confidence=None if f.confidence is None else Decimal(str(f.confidence)),
            severity=E.RiskLevel(f.severity) if f.severity else None)
        session.add(row)
        session.flush()
        for e in f.evidence:
            session.add(FindingEvidence(
                finding_id=row.id, kind=E.EvidenceKind(e.kind),
                chunk_id=UUID(e.chunk_id) if e.chunk_id else None, quote=e.quote,
                ref_json={**e.ref, **({"clause_ref": e.clause_ref} if e.clause_ref else {})}))
    for r in retrievals:
        session.add(RetrievalLog(assessment_id=a.id, query=r["query"], filters_json=r["filters"],
                                 results_json=r["results"], reranked=False))
    for c in result.llm_calls:
        session.add(LlmCall(
            assessment_id=a.id, purpose=c["purpose"], provider=c["provider"], model=c["model"],
            prompt_name=c["prompt_name"], prompt_version=c["prompt_version"], input_tokens=c.get("input_tokens"),
            output_tokens=c.get("output_tokens"), latency_ms=c.get("latency_ms"), retries=c.get("retries", 0),
            status=c["status"], error=c.get("error"),
            est_cost_usd=None if estimate_cost(settings, c.get("input_tokens"), c.get("output_tokens")) is None
            else Decimal(str(estimate_cost(settings, c.get("input_tokens"), c.get("output_tokens"))))))
    if req.status == E.RequestStatus.submitted:
        req.status = E.RequestStatus.assessed
    session.flush()
    audit.append(session, actor_type="ai", actor_id=f"{result.provider or 'rules-only'}:{result.model or '-'}",
                 action="assessment.created", entity_type="request", entity_id=str(req.id),
                 payload={"assessment_id": str(a.id), "version": version, "triggered_by": actor,
                          "status": result.compliance_status, "risk": result.overall_risk,
                          "is_mock": result.is_mock, "findings": len(result.findings),
                          "llm_claims_rejected": len(result.llm_rejected)})
    return a


def serialize_assessment(session: Session, a: Assessment) -> dict:
    findings = session.execute(select(Finding).where(Finding.assessment_id == a.id)).scalars().all()
    evidence: dict = {}
    for e in session.execute(select(FindingEvidence).where(
            FindingEvidence.finding_id.in_([f.id for f in findings] or [None]))).scalars():
        evidence.setdefault(e.finding_id, []).append(
            {"kind": e.kind.value, "chunk_id": str(e.chunk_id) if e.chunk_id else None, "quote": e.quote, "ref": e.ref_json})
    order = {c.value: i for i, c in enumerate(E.FindingCategory)}
    return {
        "id": str(a.id), "request_id": str(a.request_id), "version": a.version,
        "overall_risk": a.overall_risk.value, "compliance_status": a.compliance_status.value,
        "confidence": float(a.confidence) if a.confidence is not None else None,
        "confidence_note": "heuristic score, not a calibrated probability",
        "summary": a.summary, "is_mock": a.is_mock, "provider": a.provider, "model": a.model,
        "prompt_versions": a.prompt_versions_json, "latency_ms": a.latency_ms,
        "tokens": {"input": a.input_tokens, "output": a.output_tokens},
        "est_cost_usd": float(a.est_cost_usd) if a.est_cost_usd is not None else None,
        "created_at": a.created_at.isoformat(),
        "financial_risks": a.financial_risks_json, "next_steps": a.next_steps_json, "missing_info": a.missing_info_json,
        "findings": [
            {"id": str(f.id), "category": f.category.value, "source": f.source.value, "rule_code": f.rule_code,
             "title": f.title, "explanation": f.explanation, "severity": f.severity.value if f.severity else None,
             "confidence": float(f.confidence) if f.confidence is not None else None,
             "evidence": evidence.get(f.id, [])}
            for f in sorted(findings, key=lambda x: (order[x.category.value], x.rule_code or ""))
        ],
        "decision_required": "A human procurement officer must review this and record a decision.",
    }
