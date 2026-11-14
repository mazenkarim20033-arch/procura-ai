"""Human decisions on purchase requests: record, history, information requests and the review queue.

This is the ONLY place a request becomes approved or rejected (a test scans the code base for that), and
the database trigger additionally refuses either status without a matching decision row. AI assessments
are stored separately and are only ever shown to the reviewer as input.
Flushes only; the caller owns the transaction."""
import re
from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db import enums as E
from app.db.models import (
    Assessment,
    AuditLog,
    Decision,
    Finding,
    FindingReview,
    InfoRequest,
    PurchaseRequest,
    User,
)
from app.errors import ConflictError, NotFoundError
from app.rules.decisions import (
    AssessmentView,
    DecisionContext,
    DecisionInput,
    FindingView,
    check_decision,
)
from app.rules.policy_rules import approver_for
from app.schemas.decisions import DecisionIn
from app.schemas.identity import CurrentUser
from app.services import audit

RISK_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
REVIEWABLE = ("submitted", "assessed")


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", ".", name.casefold()).strip(".") or "user"


def ensure_user(session: Session, name: str, role: E.Role) -> User:
    """Demo identities live in headers; decisions need a users row to reference."""
    email = f"{_slug(name)}@demo.local"
    user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
    if user is None:
        user = User(email=email, name=name, role=role)
        session.add(user)
    else:
        user.role = role
    session.flush()
    return user


def _latest_assessment(session: Session, request_id: UUID) -> Assessment | None:
    return session.execute(select(Assessment).where(Assessment.request_id == request_id)
                           .order_by(Assessment.version.desc()).limit(1)).scalar_one_or_none()


def _assessment_view(session: Session, a: Assessment | None) -> AssessmentView | None:
    if a is None:
        return None
    rows = session.execute(select(Finding).where(Finding.assessment_id == a.id)).scalars().all()
    return AssessmentView(str(a.id), a.version, [FindingView(str(f.id), f.category.value, f.title) for f in rows])


def record_decision(session: Session, request_id: UUID, body: DecisionIn, user: CurrentUser) -> Decision:
    req = session.execute(select(PurchaseRequest).where(PurchaseRequest.id == request_id).with_for_update()).scalar_one_or_none()
    if not req:
        raise NotFoundError("Request not found")
    latest = _latest_assessment(session, req.id)
    inp = DecisionInput(
        action=body.action, reasoning=body.reasoning, assessment_id=str(body.assessment_id) if body.assessment_id else None,
        finding_reviews={str(r.finding_id): (r.verdict, r.note) for r in body.finding_reviews})
    ctx = DecisionContext(
        user_name=user.name, user_authority=user.authority, request_status=req.status.value,
        requester_name=req.requester_name, amount=req.total_amount, currency=req.currency,
        latest_assessment=_assessment_view(session, latest))
    check_decision(inp, ctx)

    reviewer = ensure_user(session, user.name, user.role)
    decision = Decision(request_id=req.id, assessment_id=latest.id if latest else None, reviewer_id=reviewer.id,
                        action=E.DecisionAction(body.action), reasoning=body.reasoning.strip())
    session.add(decision)
    session.flush()
    for r in body.finding_reviews:
        session.add(FindingReview(decision_id=decision.id, finding_id=r.finding_id, verdict=E.Verdict(r.verdict),
                                  note=(r.note or "").strip() or None))
    if body.action == "approve":
        req.status = E.RequestStatus.approved
    elif body.action == "reject":
        req.status = E.RequestStatus.rejected
    else:
        req.status = E.RequestStatus.info_requested
        session.add(InfoRequest(request_id=req.id, decision_id=decision.id, message=body.reasoning.strip()))
    session.flush()
    audit.append(session, actor_type="user", actor_id=user.name, action="decision.recorded", entity_type="request",
                 entity_id=str(req.id),
                 payload={"decision_id": str(decision.id), "action": body.action, "assessment_version": latest.version if latest else None,
                          "ai_status": latest.compliance_status.value if latest else None,
                          "finding_reviews": len(body.finding_reviews), "authority": user.authority})
    return decision


def respond_to_info_request(session: Session, request_id: UUID, message: str, user: CurrentUser) -> int:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    open_reqs = session.execute(select(InfoRequest).where(InfoRequest.request_id == req.id, InfoRequest.resolved_at.is_(None))).scalars().all()
    if not open_reqs:
        raise ConflictError("There is no open information request on this request")
    now = datetime.now(UTC)
    for r in open_reqs:
        r.resolved_at = now
    req.status = E.RequestStatus.submitted  # back in the queue; a new assessment is advisable
    session.flush()
    audit.append(session, actor_type="user", actor_id=user.name, action="request.info_provided", entity_type="request",
                 entity_id=str(req.id), payload={"message": message[:500], "resolved": len(open_reqs)})
    return len(open_reqs)


# ------------------------------------------------------------------ reading
def serialize_decision(session: Session, d: Decision) -> dict:
    reviewer = session.get(User, d.reviewer_id)
    a = session.get(Assessment, d.assessment_id) if d.assessment_id else None
    reviews = session.execute(select(FindingReview, Finding).join(Finding, Finding.id == FindingReview.finding_id)
                              .where(FindingReview.decision_id == d.id)).all()
    ai_status = a.compliance_status.value if a else None
    return {
        "id": str(d.id), "action": d.action.value, "reasoning": d.reasoning, "created_at": d.created_at.isoformat(),
        "actor_type": "human", "reviewer": {"name": reviewer.name, "role": reviewer.role.value} if reviewer else None,
        "ai_recommendation_at_decision": None if a is None else {
            "assessment_id": str(a.id), "version": a.version, "status": ai_status, "risk": a.overall_risk.value, "is_mock": a.is_mock},
        # The human decision stands on its own; this flag only records when it went against the AI's signal.
        "went_against_ai_signal": bool((d.action == E.DecisionAction.approve and ai_status == "issues_found")
                                       or (d.action == E.DecisionAction.reject and ai_status == "no_issues_found")),
        "finding_reviews": [{"finding_id": str(f.id), "title": f.title, "category": f.category.value,
                             "verdict": r.verdict.value, "note": r.note} for r, f in reviews],
    }


def list_decisions(session: Session, request_id: UUID) -> list[dict]:
    if not session.get(PurchaseRequest, request_id):
        raise NotFoundError("Request not found")
    rows = session.execute(select(Decision).where(Decision.request_id == request_id).order_by(Decision.created_at)).scalars().all()
    return [serialize_decision(session, d) for d in rows]


def history(session: Session, request_id: UUID) -> dict:
    req = session.get(PurchaseRequest, request_id)
    if not req:
        raise NotFoundError("Request not found")
    events = session.execute(select(AuditLog).where(AuditLog.entity_type == "request", AuditLog.entity_id == str(request_id))
                             .order_by(AuditLog.id)).scalars().all()
    infos = session.execute(select(InfoRequest).where(InfoRequest.request_id == request_id).order_by(InfoRequest.created_at)).scalars().all()
    assessments = session.execute(select(Assessment).where(Assessment.request_id == request_id).order_by(Assessment.version)).scalars().all()
    return {
        "request_id": str(req.id), "request_no": req.request_no, "status": req.status.value,
        "note": "AI assessments are recommendations; only the decisions listed are human decisions.",
        "timeline": [{"ts": e.ts.isoformat(), "actor_type": e.actor_type, "actor": e.actor_id, "action": e.action,
                      "detail": e.payload_json} for e in events],
        "ai_assessments": [{"id": str(a.id), "version": a.version, "status": a.compliance_status.value,
                            "risk": a.overall_risk.value, "is_mock": a.is_mock, "created_at": a.created_at.isoformat()} for a in assessments],
        "decisions": list_decisions(session, request_id),
        "information_requests": [{"id": str(i.id), "message": i.message, "created_at": i.created_at.isoformat(),
                                  "resolved_at": i.resolved_at.isoformat() if i.resolved_at else None} for i in infos],
        "audit_entries": len(events),
    }


def review_queue(session: Session, statuses: tuple[str, ...] = REVIEWABLE, limit: int = 100) -> list[dict]:
    reqs = session.execute(select(PurchaseRequest).where(PurchaseRequest.status.in_([E.RequestStatus(s) for s in statuses]))
                           .order_by(PurchaseRequest.submitted_at).limit(min(limit, 500))).scalars().all()
    latest_ver = dict(session.execute(select(Assessment.request_id, func.max(Assessment.version))
                                      .where(Assessment.request_id.in_([r.id for r in reqs] or [None])).group_by(Assessment.request_id)).all())
    assess = {}
    for a in session.execute(select(Assessment).where(Assessment.request_id.in_(list(latest_ver) or [None]))).scalars():
        if a.version == latest_ver.get(a.request_id):
            assess[a.request_id] = a
    counts: dict = {}
    for aid, cat, n in session.execute(select(Finding.assessment_id, Finding.category, func.count())
                                       .where(Finding.assessment_id.in_([a.id for a in assess.values()] or [None]))
                                       .group_by(Finding.assessment_id, Finding.category)).all():
        counts.setdefault(aid, {})[cat.value] = n
    open_info = {rid for (rid,) in session.execute(select(InfoRequest.request_id).where(InfoRequest.resolved_at.is_(None))).all()}
    now = datetime.now(UTC)
    out = []
    for r in reqs:
        a = assess.get(r.id)
        required = None
        if r.total_amount is not None and r.currency == "USD":
            role, ref = approver_for(Decimal(r.total_amount))
            required = {"authority": role, "clause": ref}
        out.append({
            "id": str(r.id), "request_no": r.request_no, "requester": r.requester_name, "supplier": r.supplier_name,
            "total": str(r.total_amount) if r.total_amount is not None else None, "currency": r.currency,
            "status": r.status.value, "age_days": (now - r.submitted_at).days, "has_open_info_request": r.id in open_info,
            "required_approval": required, "needs_assessment": a is None,
            "latest_assessment": None if a is None else {
                "id": str(a.id), "version": a.version, "risk": a.overall_risk.value, "status": a.compliance_status.value,
                "is_mock": a.is_mock, "findings": counts.get(a.id, {})}})
    # highest AI risk first (a signal for ordering only), then the oldest request
    out.sort(key=lambda x: (RISK_ORDER.get(x["latest_assessment"]["risk"], 4) if x["latest_assessment"] else 4, -x["age_days"]))
    return out
