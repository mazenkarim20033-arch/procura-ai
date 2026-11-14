"""Purchase request intake: create (from JSON or an extracted document), attach documents, run the
deterministic intake report. Flushes only; the caller owns the transaction."""
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import enums as E
from app.db.models import Document, Extraction, PurchaseRequest, RequestDocument, RequestItem
from app.errors import ConflictError, DomainError, NotFoundError
from app.retrieval.base import Embedder
from app.rules.intake import (
    IntakeIssue,
    ItemSnapshot,
    QuoteSnapshot,
    RequestSnapshot,
    check_request,
)
from app.schemas.requests import ItemIn, RequestCreate
from app.services import audit, vendors
from app.services.duplicates import (
    OTHER_SUPPLIER_MARGIN,
    SIMILAR_THRESHOLD,
    THRESHOLDS_USD,
    classify_duplicates,
    detect_splits,
    load_views,
)
from app.vendors.normalize import request_fingerprint


class UnprocessableDocument(DomainError):
    status_code = 422
    code = "unprocessable_document"


def _dec(value) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _date(value) -> date | None:
    try:
        return date.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def _next_request_no(session: Session) -> str:
    for _ in range(5):
        n = session.execute(text("select nextval('request_no_seq')")).scalar_one()
        candidate = f"PR-{datetime.now(UTC).year}-{n:04d}"
        if not session.execute(select(PurchaseRequest.id).where(PurchaseRequest.request_no == candidate)).first():
            return candidate
    raise ConflictError("Could not allocate a request number")


def create_request(
    session: Session, payload: RequestCreate, *, actor: str, embedder: Embedder | None,
    source_document_id: UUID | None = None, is_synthetic: bool = False,
) -> PurchaseRequest:
    if payload.request_no and session.execute(
        select(PurchaseRequest.id).where(PurchaseRequest.request_no == payload.request_no)
    ).first():
        raise ConflictError(f"Request number {payload.request_no} already exists")

    submitted = (
        datetime.combine(payload.submitted_on, datetime.min.time(), tzinfo=UTC)
        if payload.submitted_on else datetime.now(UTC)
    )
    items = [i for i in payload.items]
    req = PurchaseRequest(
        request_no=payload.request_no or _next_request_no(session), requester_name=payload.requester_name,
        department=payload.department, currency=payload.currency, supplier_name=payload.supplier_name,
        justification=payload.justification, category=payload.category, total_amount=payload.total_amount,
        status=E.RequestStatus.submitted, is_synthetic=is_synthetic, submitted_at=submitted,
        source_document_id=source_document_id,
        supplier_id=(v.id if (v := vendors.find_vendor_by_name(session, payload.supplier_name)) else None),
        fingerprint=request_fingerprint(payload.supplier_name, [(i.description or "", i.quantity) for i in items])
        if items else None,
    )
    session.add(req)
    session.flush()

    described = [i for i in items if i.description and i.description.strip()]
    vectors = embedder.embed_documents([i.description for i in described]) if (embedder and described) else []
    vec_by_id = {id(i): v for i, v in zip(described, vectors, strict=True)}
    for it in items:
        line_total = it.line_total
        if line_total is None and it.quantity is not None and it.unit_cost is not None:
            line_total = (it.quantity * it.unit_cost).quantize(Decimal("0.01"))
        session.add(RequestItem(
            request_id=req.id, description=it.description or "", quantity=it.quantity or Decimal(0),
            unit_cost=it.unit_cost, line_total=line_total, item_embedding=vec_by_id.get(id(it)),
        ))
    session.flush()
    audit.append(session, actor_type="user", actor_id=actor, action="request.created", entity_type="request",
                 entity_id=str(req.id), payload={"request_no": req.request_no, "source_document_id": str(source_document_id) if source_document_id else None})
    return req


def create_from_document(session: Session, document_id: UUID, *, actor: str, embedder: Embedder | None) -> PurchaseRequest:
    doc = session.get(Document, document_id)
    if not doc:
        raise NotFoundError("Document not found")
    if doc.doc_type != E.DocType.purchase_request:
        raise UnprocessableDocument(f"Document is classified as '{doc.doc_type.value}', not a purchase request")
    ex = session.execute(
        select(Extraction).where(Extraction.document_id == doc.id).order_by(Extraction.created_at.desc())
    ).scalars().first()
    if not ex:
        raise UnprocessableDocument("Document has no extraction")
    raw = ex.data_json
    already = session.execute(select(PurchaseRequest.id).where(PurchaseRequest.source_document_id == doc.id)).first()
    if already:
        raise ConflictError("A request was already created from this document")
    items = [ItemIn(description=i.get("description"), quantity=_dec(i.get("quantity")),
                    unit_cost=_dec(i.get("unit_price")), line_total=_dec(i.get("line_total")))
             for i in raw.get("items", [])]
    payload = RequestCreate(
        request_no=raw.get("request_no"), requester_name=raw.get("requester"), department=raw.get("department"),
        currency=raw.get("currency"), supplier_name=raw.get("supplier"), justification=raw.get("justification"),
        total_amount=_dec(raw.get("total")), submitted_on=_date(raw.get("request_date")), items=items,
    )
    req = create_request(session, payload, actor=actor, embedder=embedder, source_document_id=doc.id,
                         is_synthetic=doc.is_synthetic)
    session.add(RequestDocument(request_id=req.id, document_id=doc.id, role="request_form"))
    session.flush()
    return req


def attach_document(session: Session, request_id: UUID, document_id: UUID, role: str | None, *, actor: str) -> RequestDocument:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    doc = session.get(Document, document_id)
    if not doc:
        raise NotFoundError("Document not found")
    if session.get(RequestDocument, (request_id, document_id)):
        raise ConflictError("Document is already attached to this request")
    link = RequestDocument(request_id=request_id, document_id=document_id, role=role or doc.doc_type.value)
    session.add(link)
    session.flush()
    vendors.link_quotation_to_request(session, document_id, request_id)
    audit.append(session, actor_type="user", actor_id=actor, action="request.document_attached",
                 entity_type="request", entity_id=str(request_id),
                 payload={"document_id": str(document_id), "doc_type": doc.doc_type.value, "role": link.role})
    return link


def _snapshots(session: Session, req: PurchaseRequest) -> tuple[RequestSnapshot, list[QuoteSnapshot]]:
    items = session.execute(
        select(RequestItem).where(RequestItem.request_id == req.id).order_by(RequestItem.id)
    ).scalars().all()
    snap = RequestSnapshot(
        request_no=req.request_no, requester_name=req.requester_name, department=req.department,
        currency=req.currency, supplier_name=req.supplier_name, justification=req.justification,
        total_amount=req.total_amount, submitted_on=req.submitted_at.date() if req.submitted_at else None,
        items=[ItemSnapshot(i.description or None, i.quantity if i.quantity else None, i.unit_cost, i.line_total)
               for i in items],
    )
    docs = session.execute(
        select(Document).join(RequestDocument, RequestDocument.document_id == Document.id)
        .where(RequestDocument.request_id == req.id, Document.doc_type == E.DocType.quotation)
    ).scalars().all()
    quotes = []
    for d in docs:
        ex = session.execute(
            select(Extraction).where(Extraction.document_id == d.id).order_by(Extraction.created_at.desc())
        ).scalars().first()
        raw = ex.data_json if ex else {}
        quotes.append(QuoteSnapshot(
            document_id=str(d.id), filename=d.filename, vendor_name=raw.get("vendor_name"),
            currency=raw.get("currency"), total=_dec(raw.get("total")), issue_date=_date(raw.get("issue_date")),
            valid_until=_date(raw.get("valid_until")), quote_no=raw.get("quote_no"),
        ))
    return snap, quotes


def run_intake(session: Session, request_id: UUID) -> dict:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    snap, quotes = _snapshots(session, req)
    issues: list[IntakeIssue] = check_request(snap, quotes)

    views = load_views(session)
    target = next(v for v in views if v.id == str(req.id))
    duplicates = classify_duplicates(target, views)
    splits = detect_splits(target, views)
    if req.total_amount is not None and req.currency and req.currency != "USD":
        issues.append(IntakeIssue(
            "INT-THRESHOLD-CURRENCY", "limitation", "info", "currency",
            f"Amount thresholds and split-purchase checks use USD; no exchange-rate source is configured, "
            f"so a {req.currency} request cannot be checked against them"))
    if target.item_vectors == [] and snap.items:
        issues.append(IntakeIssue(
            "INT-NO-EMBEDDINGS", "limitation", "info", "items",
            "Item embeddings are missing, so similarity-based duplicate detection only used exact matches"))

    by_kind: dict[str, int] = {}
    for i in issues:
        by_kind[i.kind] = by_kind.get(i.kind, 0) + 1
    return {
        "request_id": str(req.id), "request_no": req.request_no, "status": req.status.value,
        "generated_by": "deterministic intake rules (no LLM)",
        "summary": {"issues": len(issues), "by_kind": by_kind, "errors": sum(i.severity == "error" for i in issues),
                    "possible_duplicates": len(duplicates), "split_findings": len(splits),
                    "quotations_attached": len(quotes)},
        "issues": [i.as_dict() for i in issues],
        "duplicates": [d.as_dict() for d in duplicates],
        "splits": [s.as_dict() for s in splits],
        "parameters": {"similar_threshold": SIMILAR_THRESHOLD, "other_supplier_margin": OTHER_SUPPLIER_MARGIN,
                       "usd_thresholds": [str(t) for t in THRESHOLDS_USD]},
    }
