from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, require_role
from app.db import enums as E
from app.db.session import get_session
from app.retrieval.embedders import get_embedder
from app.services import vendors as svc

router = APIRouter(tags=["vendors"])


class MergeBody(BaseModel):
    into_vendor_id: UUID


@router.get("/vendors")
def list_vendors(session: Session = Depends(get_session)) -> list[dict]:
    """Vendor records built from uploaded documents only; no external verification."""
    return svc.list_vendors(session)


@router.get("/vendors/{vendor_id}")
def get_vendor(vendor_id: UUID, session: Session = Depends(get_session)) -> dict:
    return svc.vendor_detail(session, vendor_id)


@router.post("/vendors/{vendor_id}/merge")
def merge_vendor(
    vendor_id: UUID, body: MergeBody, user: CurrentUser = Depends(require_role(E.Role.admin)),
    session: Session = Depends(get_session),
) -> dict:
    """Admin: fold a duplicate vendor record into another (e.g. after reviewing a fuzzy name match)."""
    dst = svc.merge_vendors(session, vendor_id, body.into_vendor_id, actor=user.name)
    session.commit()
    return svc.vendor_detail(session, dst.id)


@router.get("/requests/{request_id}/quote-comparison")
def quote_comparison(request_id: UUID, session: Session = Depends(get_session)) -> dict:
    return svc.build_comparison(session, request_id, get_embedder())
