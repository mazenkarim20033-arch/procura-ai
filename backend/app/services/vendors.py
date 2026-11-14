"""Vendor records built from uploaded documents, quotation storage and quote comparison.

Everything here is derived from the documents the user uploaded. No external supplier verification,
registry or market-data source exists, and no result may be presented as if one did.
Flushes only; the caller owns the transaction."""
from datetime import date
from decimal import Decimal, InvalidOperation
from uuid import UUID

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import enums as E
from app.db.models import (
    Document,
    Extraction,
    PurchaseRequest,
    Quotation,
    QuotationItem,
    RequestItem,
    Vendor,
    VendorAlias,
)
from app.errors import ConflictError, NotFoundError
from app.retrieval.base import Embedder
from app.services import audit
from app.vendors.compare import BASIS, HistoryPoint, ItemQ, QuoteQ, compare_quotes
from app.vendors.normalize import normalize_vendor_name
from app.vendors.resolve import Candidate, MatchDecision, Profile, resolve_vendor

PROFILE_FIELDS = ("tax_id", "email", "phone", "address", "country")


def _dec(v) -> Decimal | None:
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v))
    except InvalidOperation:
        return None


def _date(v) -> date | None:
    try:
        return date.fromisoformat(str(v)) if v else None
    except ValueError:
        return None


def issue_codes(validation_issues: list[dict]) -> list[str]:
    out = []
    for i in validation_issues or []:
        if i.get("code") in {"missing_field", "invalid_value"}:
            out.append(f"{i['code']}:{i['field']}")
        elif i.get("code") != "parse_warning":
            out.append(i["code"])
    return out


# ------------------------------------------------------------------ vendor records
def _candidates(session: Session) -> list[Candidate]:
    aliases: dict = {}
    for a in session.execute(select(VendorAlias)).scalars():
        aliases.setdefault(a.vendor_id, []).append(a.alias)
    return [Candidate(str(v.id), v.canonical_name, v.tax_id, aliases.get(v.id, []))
            for v in session.execute(select(Vendor)).scalars()]


def find_vendor_by_name(session: Session, name: str | None) -> Vendor | None:
    """Exact normalised-name or alias match only (no fuzzy matching, no creation)."""
    d = resolve_vendor(Profile(name or ""), _candidates(session), fuzzy_threshold=2.0)
    return session.get(Vendor, UUID(d.vendor_id)) if d.action == "match" else None


def record_vendor(session: Session, *, name: str | None, doc_id: UUID | None, **profile) -> tuple[Vendor | None, MatchDecision | None]:
    name = (name or "").strip()
    if not normalize_vendor_name(name):
        return None, None
    decision = resolve_vendor(Profile(name, profile.get("tax_id")), _candidates(session))
    contact_in = {k: profile.get(k) for k in ("email", "phone", "address") if profile.get(k)}
    if decision.action == "new":
        v = Vendor(canonical_name=name, normalized_name=normalize_vendor_name(name), tax_id=profile.get("tax_id"),
                   country=profile.get("country"), contact_json=contact_in, first_seen_doc_id=doc_id)
        session.add(v)
        session.flush()
        return v, decision

    v = session.get(Vendor, UUID(decision.vendor_id))
    contact = dict(v.contact_json or {})
    if normalize_vendor_name(name) != v.normalized_name and name != v.canonical_name:
        exists = session.execute(select(VendorAlias).where(VendorAlias.vendor_id == v.id, VendorAlias.alias == name)).first()
        if not exists:
            session.add(VendorAlias(vendor_id=v.id, alias=name, source_doc_id=doc_id))
        if decision.reason == "fuzzy":
            contact.setdefault("alias_review", []).append({"alias": name, "score": decision.score, "doc_id": str(doc_id) if doc_id else None})
    for k, val in contact_in.items():
        contact.setdefault(k, val)
    if profile.get("tax_id") and not v.tax_id:
        v.tax_id = profile["tax_id"]
    if profile.get("country") and not v.country:
        v.country = profile["country"]
    for c in decision.conflicts:
        entry = {**c, "doc_id": str(doc_id) if doc_id else None}
        if entry not in contact.get("conflicts", []):
            contact.setdefault("conflicts", []).append(entry)
    v.contact_json = contact
    session.flush()
    return v, decision


def record_from_document(session: Session, doc: Document, raw: dict, validation: list[dict]) -> Vendor | None:
    """Create/update the vendor named in a quotation, invoice or contract; store quotation rows."""
    vendor, _ = record_vendor(
        session, name=raw.get("vendor_name"), doc_id=doc.id, tax_id=raw.get("vendor_tax_id"),
        email=raw.get("vendor_email"), phone=raw.get("vendor_phone"), address=raw.get("vendor_address"),
        country=raw.get("vendor_country"))
    if vendor and doc.doc_type == E.DocType.quotation and not session.execute(
            select(Quotation.id).where(Quotation.document_id == doc.id)).first():
        q = Quotation(
            vendor_id=vendor.id, document_id=doc.id, quote_no=raw.get("quote_no"), issue_date=_date(raw.get("issue_date")),
            valid_until=_date(raw.get("valid_until")), currency=raw.get("currency"), subtotal=_dec(raw.get("subtotal")),
            tax=_dec(raw.get("tax")), total=_dec(raw.get("total")), payment_terms=raw.get("payment_terms"),
            delivery_days=raw.get("delivery_days") if isinstance(raw.get("delivery_days"), int) else None)
        session.add(q)
        session.flush()
        for it in raw.get("items", []):
            session.add(QuotationItem(quotation_id=q.id, description=it.get("description") or "",
                                      quantity=_dec(it.get("quantity")) or Decimal(0), unit_price=_dec(it.get("unit_price")),
                                      line_total=_dec(it.get("line_total"))))
        session.flush()
    return vendor


def link_quotation_to_request(session: Session, document_id: UUID, request_id: UUID) -> None:
    q = session.execute(select(Quotation).where(Quotation.document_id == document_id)).scalars().first()
    if q is not None and q.request_id is None:
        q.request_id = request_id
        session.flush()


# ------------------------------------------------------------------ gaps, listing, merge
def profile_gaps(v: Vendor, doc_count: int) -> list[dict]:
    contact = v.contact_json or {}
    gaps = []
    for label, present in (("tax ID", bool(v.tax_id)), ("email", bool(contact.get("email"))),
                           ("phone", bool(contact.get("phone"))), ("address", bool(contact.get("address"))),
                           ("country", bool(v.country))):
        if not present:
            gaps.append({"code": f"VND-MISSING-{label.upper().replace(' ', '_')}",
                         "severity": "warning" if label == "tax ID" else "info",
                         "message": f"No {label} appears on any of the {doc_count} uploaded document(s) from this vendor"})
    for c in contact.get("conflicts", []):
        gaps.append({"code": "VND-CONFLICT", "severity": "warning",
                     "message": f"Conflicting {c['field']}: {c['existing']} vs {c['new']} in different documents"})
    for r in contact.get("alias_review", []):
        gaps.append({"code": "VND-ALIAS-REVIEW", "severity": "info",
                     "message": f"Name '{r['alias']}' was matched to this vendor by similarity ({r['score']}); confirm it is the same company"})
    return gaps


def _doc_counts(session: Session) -> dict:
    out: dict = {}
    for vid, _qid in session.execute(select(Quotation.vendor_id, Quotation.id)).all():
        out[vid] = out.get(vid, 0) + 1
    return out


def list_vendors(session: Session) -> list[dict]:
    counts = _doc_counts(session)
    rows = session.execute(select(Vendor).order_by(Vendor.canonical_name)).scalars().all()
    return [{"id": str(v.id), "name": v.canonical_name, "country": v.country, "tax_id": v.tax_id,
             "quotations": counts.get(v.id, 0), "gaps": len(profile_gaps(v, counts.get(v.id, 0))),
             "basis": BASIS} for v in rows]


def vendor_detail(session: Session, vendor_id: UUID) -> dict:
    v = session.get(Vendor, vendor_id)
    if not v:
        raise NotFoundError("Vendor not found")
    aliases = [a.alias for a in session.execute(select(VendorAlias).where(VendorAlias.vendor_id == v.id)).scalars()]
    quotes = session.execute(select(Quotation).where(Quotation.vendor_id == v.id).order_by(Quotation.issue_date)).scalars().all()
    return {
        "id": str(v.id), "name": v.canonical_name, "normalized_name": v.normalized_name, "aliases": aliases,
        "tax_id": v.tax_id, "country": v.country, "contact": {k: x for k, x in (v.contact_json or {}).items()
                                                               if k in {"email", "phone", "address"}},
        "gaps": profile_gaps(v, len(quotes)), "basis": BASIS,
        "quotations": [{"id": str(q.id), "quote_no": q.quote_no, "issue_date": q.issue_date.isoformat() if q.issue_date else None,
                        "currency": q.currency, "total": str(q.total) if q.total is not None else None,
                        "payment_terms": q.payment_terms, "request_id": str(q.request_id) if q.request_id else None}
                       for q in quotes],
    }


def merge_vendors(session: Session, from_id: UUID, into_id: UUID, *, actor: str) -> Vendor:
    if from_id == into_id:
        raise ConflictError("Cannot merge a vendor into itself")
    src, dst = session.get(Vendor, from_id), session.get(Vendor, into_id)
    if not src or not dst:
        raise NotFoundError("Vendor not found")
    for q in session.execute(select(Quotation).where(Quotation.vendor_id == src.id)).scalars():
        q.vendor_id = dst.id
    for r in session.execute(select(PurchaseRequest).where(PurchaseRequest.supplier_id == src.id)).scalars():
        r.supplier_id = dst.id
    existing = {a.alias for a in session.execute(select(VendorAlias).where(VendorAlias.vendor_id == dst.id)).scalars()}
    for a in session.execute(select(VendorAlias).where(VendorAlias.vendor_id == src.id)).scalars():
        if a.alias in existing or a.alias == dst.canonical_name:
            session.delete(a)
        else:
            a.vendor_id = dst.id
            existing.add(a.alias)
    if src.canonical_name not in existing and src.canonical_name != dst.canonical_name:
        session.add(VendorAlias(vendor_id=dst.id, alias=src.canonical_name, source_doc_id=src.first_seen_doc_id))
    contact = dict(dst.contact_json or {})
    for k, val in (src.contact_json or {}).items():
        if k in {"conflicts", "alias_review"}:
            contact.setdefault(k, []).extend(val)
        else:
            contact.setdefault(k, val)
    if src.tax_id and dst.tax_id and src.tax_id != dst.tax_id:
        contact.setdefault("conflicts", []).append({"field": "tax_id", "existing": dst.tax_id, "new": src.tax_id, "doc_id": None})
    dst.tax_id = dst.tax_id or src.tax_id
    dst.country = dst.country or src.country
    dst.contact_json = contact
    session.flush()
    session.delete(src)
    audit.append(session, actor_type="user", actor_id=actor, action="vendor.merged", entity_type="vendor",
                 entity_id=str(dst.id), payload={"merged_from": str(from_id), "into": str(into_id)})
    session.flush()
    return dst


# ------------------------------------------------------------------ comparison
def _vec(vectors: dict, text: str):
    v = vectors.get(text)
    return None if v is None else np.asarray(v, dtype=float)


def build_comparison(session: Session, request_id: UUID, embedder: Embedder | None) -> dict:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    qrows = session.execute(select(Quotation).where(Quotation.request_id == request_id)).scalars().all()
    docs = {d.id: d for d in session.execute(select(Document).where(Document.id.in_([q.document_id for q in qrows] or [None]))).scalars()}
    vendors = {v.id: v for v in session.execute(select(Vendor).where(Vendor.id.in_([q.vendor_id for q in qrows if q.vendor_id] or [None]))).scalars()}
    items_by_q: dict = {}
    for it in session.execute(select(QuotationItem).where(QuotationItem.quotation_id.in_([q.id for q in qrows] or [None]))).scalars():
        items_by_q.setdefault(it.quotation_id, []).append(it)

    # history: the same vendors' items from quotations that are not part of this comparison
    hist_rows = []
    if qrows:
        vids = [q.vendor_id for q in qrows if q.vendor_id]
        for q in session.execute(select(Quotation).where(Quotation.vendor_id.in_(vids or [None]),
                                                         Quotation.id.not_in([x.id for x in qrows]))).scalars():
            for it in session.execute(select(QuotationItem).where(QuotationItem.quotation_id == q.id)).scalars():
                if it.unit_price is not None:
                    hist_rows.append((q, it))

    texts = sorted({it.description for items in items_by_q.values() for it in items} | {it.description for _, it in hist_rows})
    vectors = dict(zip(texts, embedder.embed_documents(texts), strict=True)) if (embedder and texts) else {}

    quotes = []
    for q in qrows:
        extraction = session.execute(select(Extraction).where(Extraction.document_id == q.document_id)
                                     .order_by(Extraction.created_at.desc())).scalars().first()
        key = str(q.vendor_id) if q.vendor_id else normalize_vendor_name(docs[q.document_id].filename)
        quotes.append(QuoteQ(
            key=key, vendor_name=vendors[q.vendor_id].canonical_name if q.vendor_id in vendors else "unknown vendor",
            label=docs[q.document_id].filename, currency=q.currency, total=q.total, subtotal=q.subtotal, tax=q.tax,
            delivery_days=q.delivery_days, payment_terms=q.payment_terms, issue_date=q.issue_date, valid_until=q.valid_until,
            items=[ItemQ(i.description, i.quantity, i.unit_price, i.line_total, _vec(vectors, i.description))
                   for i in items_by_q.get(q.id, [])],
            issue_codes=issue_codes(extraction.validation_errors_json) if extraction else []))
    history = [HistoryPoint(str(q.vendor_id), it.description, it.unit_price, q.currency, q.issue_date, _vec(vectors, it.description))
               for q, it in hist_rows]
    res = compare_quotes(quotes, req.submitted_at.date() if req.submitted_at else None,
                         request_currency=req.currency, history=history)
    req_items = session.execute(select(RequestItem).where(RequestItem.request_id == req.id)).scalars().all()
    res["request"] = {"request_no": req.request_no, "currency": req.currency, "supplier_name": req.supplier_name,
                      "estimated_total": str(req.total_amount) if req.total_amount is not None else None,
                      "items": [i.description for i in req_items]}
    return res
