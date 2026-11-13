from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.providers.factory import build_provider
from app.api.auth import CurrentUser, require_role
from app.db import enums as E
from app.db.models import Assessment, PurchaseRequest
from app.db.session import get_session
from app.errors import NotFoundError
from app.retrieval.embedders import get_embedder
from app.services import assessment as svc

router = APIRouter(tags=["assessments"])


class ApprovedSuppliers(BaseModel):
    names: list[str] = Field(max_length=500)


@router.post("/requests/{request_id}/assess", status_code=201)
def assess_request(
    request_id: UUID, user: CurrentUser = Depends(require_role(E.Role.reviewer)),
    session: Session = Depends(get_session),
) -> dict:
    """Run the AI-assisted pre-assessment. It never approves or rejects: a human decides afterwards."""
    a = svc.assess_request(session, request_id, provider=build_provider(), embedder=get_embedder(), actor=user.name)
    session.commit()
    return svc.serialize_assessment(session, a)


@router.get("/requests/{request_id}/assessments")
def list_assessments(request_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    if not session.get(PurchaseRequest, request_id):
        raise NotFoundError("Request not found")
    rows = session.execute(select(Assessment).where(Assessment.request_id == request_id)
                           .order_by(Assessment.version.desc())).scalars().all()
    return [{"id": str(a.id), "version": a.version, "overall_risk": a.overall_risk.value,
             "compliance_status": a.compliance_status.value, "is_mock": a.is_mock, "provider": a.provider,
             "created_at": a.created_at.isoformat()} for a in rows]


@router.get("/assessments/{assessment_id}")
def get_assessment(assessment_id: UUID, session: Session = Depends(get_session)) -> dict:
    a = session.get(Assessment, assessment_id)
    if not a:
        raise NotFoundError("Assessment not found")
    return svc.serialize_assessment(session, a)


@router.get("/settings/approved-suppliers")
def get_approved(session: Session = Depends(get_session)) -> dict:
    names = svc.get_approved_suppliers(session)
    return {"configured": names is not None, "names": names or []}


@router.put("/settings/approved-suppliers")
def put_approved(
    body: ApprovedSuppliers, user: CurrentUser = Depends(require_role(E.Role.admin)),
    session: Session = Depends(get_session),
) -> dict:
    names = svc.set_approved_suppliers(session, body.names, actor=user.name)
    session.commit()
    return {"configured": True, "names": names}
