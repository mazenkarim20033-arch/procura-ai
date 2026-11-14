from uuid import UUID

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, get_current_user, require_role
from app.db import enums as E
from app.db.session import get_session
from app.schemas.decisions import DecisionIn, InfoResponseIn
from app.services import decisions as svc

router = APIRouter(tags=["decisions"])


@router.post("/requests/{request_id}/decisions", status_code=201)
def record_decision(
    request_id: UUID, body: DecisionIn, user: CurrentUser = Depends(require_role(E.Role.reviewer)),
    session: Session = Depends(get_session),
) -> dict:
    """A human reviewer's decision. It is stored separately from AI assessments and is the only way a request
    becomes approved or rejected."""
    d = svc.record_decision(session, request_id, body, user)
    session.commit()
    return svc.serialize_decision(session, d)


@router.get("/requests/{request_id}/decisions")
def list_decisions(request_id: UUID, session: Session = Depends(get_session)) -> list[dict]:
    return svc.list_decisions(session, request_id)


@router.get("/requests/{request_id}/history")
def request_history(request_id: UUID, session: Session = Depends(get_session)) -> dict:
    """Timeline (audit-log backed), AI assessments and human decisions, kept in separate lists."""
    return svc.history(session, request_id)


@router.post("/requests/{request_id}/info-response")
def info_response(
    request_id: UUID, body: InfoResponseIn, user: CurrentUser = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    resolved = svc.respond_to_info_request(session, request_id, body.message, user)
    session.commit()
    return {"resolved_requests": resolved, "status": "submitted"}


@router.get("/review/queue")
def review_queue(
    status: str = Query(default="submitted,assessed"), limit: int = 100,
    _: CurrentUser = Depends(require_role(E.Role.reviewer)), session: Session = Depends(get_session),
) -> list[dict]:
    statuses = tuple(s.strip() for s in status.split(",") if s.strip())
    return svc.review_queue(session, statuses, limit)
