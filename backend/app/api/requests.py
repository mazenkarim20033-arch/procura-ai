from uuid import UUID

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, get_current_user
from app.db import enums as E
from app.db.models import Document, PurchaseRequest, RequestDocument, RequestItem
from app.db.session import get_session
from app.errors import NotFoundError
from app.retrieval.embedders import get_embedder
from app.schemas.requests import AttachDocument, RequestCreate
from app.services import requests as svc

router = APIRouter(prefix="/requests", tags=["requests"])


def _summary(r: PurchaseRequest) -> dict:
    return {
        "id": str(r.id), "request_no": r.request_no, "requester_name": r.requester_name,
        "department": r.department, "supplier_name": r.supplier_name, "currency": r.currency,
        "total_amount": str(r.total_amount) if r.total_amount is not None else None,
        "status": r.status.value, "submitted_at": r.submitted_at.isoformat(), "is_synthetic": r.is_synthetic,
    }


@router.post("", status_code=201)
def create_request(
    body: RequestCreate, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
) -> dict:
    req = svc.create_request(session, body, actor=user.name, embedder=get_embedder())
    session.commit()
    return _summary(req)


@router.post("/from-document/{document_id}", status_code=201)
def create_from_document(
    document_id: UUID, user: CurrentUser = Depends(get_current_user), session: Session = Depends(get_session),
) -> dict:
    req = svc.create_from_document(session, document_id, actor=user.name, embedder=get_embedder())
    session.commit()
    return _summary(req)


@router.get("")
def list_requests(
    status: str | None = None, limit: int = 100, session: Session = Depends(get_session),
) -> list[dict]:
    q = select(PurchaseRequest).order_by(PurchaseRequest.submitted_at.desc()).limit(min(limit, 500))
    if status:
        q = q.where(PurchaseRequest.status == E.RequestStatus(status))
    return [_summary(r) for r in session.execute(q).scalars()]


@router.get("/{request_id}")
def get_request(request_id: UUID, session: Session = Depends(get_session)) -> dict:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    items = session.execute(
        select(RequestItem).where(RequestItem.request_id == req.id).order_by(RequestItem.id)
    ).scalars().all()
    docs = session.execute(
        select(Document, RequestDocument.role).join(RequestDocument, RequestDocument.document_id == Document.id)
        .where(RequestDocument.request_id == req.id)
    ).all()
    return {
        **_summary(req), "justification": req.justification, "category": req.category,
        "items": [{"description": i.description, "quantity": str(i.quantity),
                   "unit_cost": str(i.unit_cost) if i.unit_cost is not None else None,
                   "line_total": str(i.line_total) if i.line_total is not None else None} for i in items],
        "documents": [{"id": str(d.id), "filename": d.filename, "doc_type": d.doc_type.value, "role": role}
                      for d, role in docs],
    }


@router.post("/{request_id}/documents", status_code=201)
def attach_document(
    request_id: UUID, body: AttachDocument, user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    try:
        doc_id = UUID(body.document_id)
    except ValueError:
        raise NotFoundError("Document not found") from None
    link = svc.attach_document(session, request_id, doc_id, body.role, actor=user.name)
    session.commit()
    return {"request_id": str(link.request_id), "document_id": str(link.document_id), "role": link.role}


@router.get("/{request_id}/intake")
def intake_report(request_id: UUID, session: Session = Depends(get_session)) -> dict:
    """Deterministic checks: missing information, inconsistencies, duplicates, split purchases."""
    return svc.run_intake(session, request_id)
