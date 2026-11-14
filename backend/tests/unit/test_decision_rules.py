from decimal import Decimal

import pytest

from app.errors import ConflictError, PermissionDeniedError
from app.rules.decisions import (
    AssessmentView,
    DecisionContext,
    DecisionInput,
    FindingView,
    UnprocessableDecision,
    check_decision,
)

D = Decimal
REASON = "Reviewed the evidence and quotations."


def assessment(*cats) -> AssessmentView:
    return AssessmentView("A1", 2, [FindingView(f"F{i}", c, f"finding {i}") for i, c in enumerate(cats)])


def ctx(**kw) -> DecisionContext:
    base = dict(user_name="Rev", user_authority="finance director", request_status="assessed", requester_name="Layla",
                amount=D("12000"), currency="USD", latest_assessment=assessment("compliant"))
    base.update(kw)
    return DecisionContext(**base)


def decision(action="approve", reasoning=REASON, assessment_id="A1", reviews=None) -> DecisionInput:
    return DecisionInput(action, reasoning, assessment_id, reviews or {})


def test_clean_approval_by_sufficient_authority_is_allowed():
    check_decision(decision(), ctx())
    check_decision(decision("reject"), ctx(user_authority="department manager"))  # rejecting needs no level


def test_requester_cannot_decide_on_their_own_request():
    for action in ("approve", "reject", "request_info"):
        with pytest.raises(PermissionDeniedError, match="PRC-001:3.1"):
            check_decision(decision(action), ctx(user_name="  layla "))


def test_reasoning_is_mandatory_for_every_action():
    for action in ("approve", "reject", "request_info"):
        with pytest.raises(UnprocessableDecision, match="PRC-001:3.2"):
            check_decision(decision(action, reasoning="  ok  "), ctx())


def test_decisions_on_final_requests_are_refused():
    for status in ("approved", "rejected"):
        with pytest.raises(ConflictError, match="final"):
            check_decision(decision(), ctx(request_status=status))


def test_unknown_action_and_missing_or_stale_assessment():
    with pytest.raises(UnprocessableDecision):
        check_decision(decision("maybe"), ctx())
    with pytest.raises(ConflictError, match="Run the AI assessment first"):
        check_decision(decision(), ctx(latest_assessment=None))
    with pytest.raises(ConflictError, match="different assessment"):
        check_decision(decision(assessment_id="OLD"), ctx())
    with pytest.raises(ConflictError, match="different assessment"):
        check_decision(decision(assessment_id=None), ctx())
    check_decision(decision("request_info", assessment_id=None), ctx(latest_assessment=None))  # asking for info needs none


def test_approval_level_follows_the_amount():
    cases = [("500", "department manager", True), ("1000", "department manager", True), ("1000.01", "department manager", False),
             ("9000", "procurement officer", True), ("12000", "procurement officer", False),
             ("50000", "finance director", True), ("50001", "finance director", False), ("900000", "chief financial officer", True)]
    for amount, authority, allowed in cases:
        c = ctx(amount=D(amount), user_authority=authority)
        if allowed:
            check_decision(decision(), c)
        else:
            with pytest.raises(PermissionDeniedError, match="must be approved by"):
                check_decision(decision(), c)
    with pytest.raises(PermissionDeniedError):
        check_decision(decision(), ctx(user_authority=None))


def test_unknown_amount_or_non_usd_can_only_be_approved_by_the_top_authority():
    for kw in ({"amount": None}, {"currency": "EUR"}):
        with pytest.raises(PermissionDeniedError, match="cannot be determined"):
            check_decision(decision(), ctx(**kw))
        check_decision(decision(), ctx(user_authority="chief financial officer", **kw))
        check_decision(decision("reject"), ctx(**kw))  # rejecting is always possible


def test_approving_over_confirmed_violations_requires_a_documented_override_of_each():
    a = assessment("confirmed_violation", "confirmed_violation", "potential_violation")
    c = ctx(latest_assessment=a)
    with pytest.raises(ConflictError, match="finding 0; finding 1"):
        check_decision(decision(), c)
    with pytest.raises(ConflictError):  # agreeing with a violation and approving is a contradiction
        check_decision(decision(reviews={"F0": ("agree", "This is a real problem here"), "F1": ("disagree", "Supplier fixed this")}), c)
    with pytest.raises(ConflictError):  # a one-word note is not a justification
        check_decision(decision(reviews={"F0": ("disagree", "no"), "F1": ("disagree", "no")}), c)
    check_decision(decision(reviews={"F0": ("disagree", "Supplier corrected the quote on 3 March"),
                                     "F1": ("disagree", "Validity extended by email, attached")}), c)
    check_decision(decision("reject"), c)  # rejecting needs no override


def test_finding_reviews_must_belong_to_the_assessment():
    with pytest.raises(UnprocessableDecision, match="not in this assessment"):
        check_decision(decision("reject", reviews={"F99": ("agree", None)}), ctx())
