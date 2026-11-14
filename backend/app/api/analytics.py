from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, require_role
from app.db import enums as E
from app.db.session import get_session
from app.services import analytics, audit

router = APIRouter(tags=["analytics"])


@router.get("/analytics/overview")
def analytics_overview(
    since: date | None = None, until: date | None = None, exclude_mock: bool = False,
    _: CurrentUser = Depends(require_role(E.Role.reviewer)), session: Session = Depends(get_session),
) -> dict:
    """Live statistics (reviewer/admin). Each figure comes with its sample size; see `definitions`."""
    return analytics.overview(session, since=since, until=until, exclude_mock=exclude_mock)


@router.get("/audit")
def audit_entries(
    entity_type: str | None = None, entity_id: str | None = None, action: str | None = None,
    actor_type: str | None = Query(default=None, pattern="^(user|system|ai)$"), before_id: int | None = None,
    limit: int = 50, _: CurrentUser = Depends(require_role(E.Role.reviewer)), session: Session = Depends(get_session),
) -> dict:
    """Append-only, hash-chained audit trail, newest first."""
    return audit.list_entries(session, entity_type=entity_type, entity_id=entity_id, action=action,
                              actor_type=actor_type, before_id=before_id, limit=limit)


@router.get("/audit/verify")
def audit_verify(_: CurrentUser = Depends(require_role(E.Role.reviewer)), session: Session = Depends(get_session)) -> dict:
    """Recompute every hash in the chain. Tamper-evident, not tamper-proof (see `scope`)."""
    return audit.verify_all(session)
