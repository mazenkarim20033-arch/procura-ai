"""Rules a human decision must satisfy. Pure functions, no database.

Sources (synthetic policies): PRC-001 2.1-2.4 approval levels by amount, PRC-001 3.1 the requester must not
approve their own purchase, PRC-001 3.2 approvers record written reasoning. The AI assessment informs the
reviewer but never decides: nothing in this module or the system lets an assessment change a request's
final status.
"""
from dataclasses import dataclass, field
from decimal import Decimal

from app.errors import ConflictError, DomainError, PermissionDeniedError
from app.rules.authority import AUTHORITY_ORDER, authority_rank
from app.rules.policy_rules import approver_for

MIN_REASONING = 10
MIN_OVERRIDE_NOTE = 10


class UnprocessableDecision(DomainError):
    status_code = 422
    code = "invalid_decision"


@dataclass
class FindingView:
    id: str
    category: str
    title: str


@dataclass
class AssessmentView:
    id: str
    version: int
    findings: list[FindingView] = field(default_factory=list)


@dataclass
class DecisionInput:
    action: str  # approve | reject | request_info
    reasoning: str
    assessment_id: str | None = None
    finding_reviews: dict[str, tuple[str, str | None]] = field(default_factory=dict)  # finding id -> (verdict, note)


@dataclass
class DecisionContext:
    user_name: str
    user_authority: str | None
    request_status: str
    requester_name: str | None
    amount: Decimal | None
    currency: str | None
    latest_assessment: AssessmentView | None


def _same_person(a: str | None, b: str | None) -> bool:
    return bool(a and b and a.strip().casefold() == b.strip().casefold())


def check_decision(inp: DecisionInput, ctx: DecisionContext) -> None:
    """Raise a DomainError describing the first violated rule; return None when the decision may be recorded."""
    if inp.action not in {"approve", "reject", "request_info"}:
        raise UnprocessableDecision(f"Unknown action '{inp.action}'")
    if _same_person(ctx.user_name, ctx.requester_name):
        raise PermissionDeniedError("Segregation of duties (PRC-001:3.1): you cannot decide on your own purchase request")
    if ctx.request_status in {"approved", "rejected"}:
        raise ConflictError(f"The request is already {ctx.request_status}; decisions are final")
    if len((inp.reasoning or "").strip()) < MIN_REASONING:
        raise UnprocessableDecision(
            f"PRC-001:3.2 requires written reasoning for every decision (at least {MIN_REASONING} characters)")
    if inp.action == "request_info":
        return

    a = ctx.latest_assessment
    if a is None:
        raise ConflictError("Run the AI assessment first: a decision must be made with the evidence in front of you")
    if inp.assessment_id != a.id:
        raise ConflictError(f"This decision refers to a different assessment; the latest is version {a.version} (id {a.id})")
    unknown = set(inp.finding_reviews) - {f.id for f in a.findings}
    if unknown:
        raise UnprocessableDecision(f"Finding reviews refer to findings that are not in this assessment: {sorted(unknown)}")
    if inp.action == "reject":
        return

    # ---- approve: authority first, then unresolved confirmed violations
    if ctx.amount is not None and ctx.currency == "USD":
        role, ref = approver_for(ctx.amount)
        if authority_rank(ctx.user_authority) < AUTHORITY_ORDER.index(role):
            raise PermissionDeniedError(
                f"A USD {ctx.amount:,.2f} purchase must be approved by the {role} or higher ({ref}); "
                f"your authority is {ctx.user_authority or 'none'}")
    elif ctx.user_authority != AUTHORITY_ORDER[-1]:
        raise PermissionDeniedError(
            "The approval level cannot be determined (the amount is missing or not in USD, and no exchange rate source "
            "exists); only the chief financial officer may approve, others can reject or request information")

    unresolved = []
    for f in a.findings:
        if f.category != "confirmed_violation":
            continue
        verdict, note = inp.finding_reviews.get(f.id, (None, None))
        if verdict != "disagree" or len((note or "").strip()) < MIN_OVERRIDE_NOTE:
            unresolved.append(f.title)
    if unresolved:
        raise ConflictError(
            "Cannot approve over confirmed violations without overriding each one (verdict 'disagree' plus a note of at "
            f"least {MIN_OVERRIDE_NOTE} characters explaining why). Unresolved: " + "; ".join(unresolved))
