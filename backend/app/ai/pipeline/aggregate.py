"""Deterministic aggregation of findings into risk, status, confidence, financial risks and next steps.
Weights are documented heuristics, not calibrated probabilities."""
from decimal import Decimal

from app.ai.pipeline.context import AssessmentContext
from app.rules.policy_rules import (
    COMPLIANT,
    CONFIRMED,
    INCONCLUSIVE,
    MISSING,
    POTENTIAL,
    RuleFinding,
    approver_for,
    parse_terms,
)

WEIGHTS = {CONFIRMED: 3.0, POTENTIAL: 1.5, MISSING: 1.0, INCONCLUSIVE: 0.5, COMPLIANT: 0.0}
RISK_BANDS = [(1.0, "low"), (3.0, "medium"), (6.0, "high")]  # score < bound -> label, else "critical"
CORE_CHECKS = {"R-QUOTE-COUNT", "R-JUSTIFICATION"}  # must have run for "no_issues_found"


def risk_from_score(score: float) -> str:
    for bound, label in RISK_BANDS:
        if score < bound:
            return label
    return "critical"


def aggregate(findings: list[RuleFinding], ran: set[str], ctx: AssessmentContext, *, llm_dropped: int,
              relevance_ok: bool) -> dict:
    counts = {c: sum(f.category == c for f in findings) for c in WEIGHTS}
    score = sum(WEIGHTS[f.category] for f in findings)
    if counts[CONFIRMED] and ctx.request.total_amount and ctx.request.currency == "USD" \
            and ctx.request.total_amount > Decimal(25000):
        score += 1.0  # confirmed violations on large spend weigh more
    risk = risk_from_score(score)

    if counts[CONFIRMED] or counts[POTENTIAL]:
        status = "issues_found"
    elif counts[MISSING]:
        status = "needs_information"
    elif counts[INCONCLUSIVE] or not CORE_CHECKS <= ran:
        status = "inconclusive"
    else:
        status = "no_issues_found"

    confidence = 1.0 - 0.15 * counts[INCONCLUSIVE] - 0.1 * counts[MISSING] - 0.2 * llm_dropped \
        - (0 if relevance_ok else 0.2)
    confidence = round(max(0.1, min(1.0, confidence)), 2)

    summary = (f"Automated pre-assessment, not a decision. {len(findings)} finding(s): "
               f"{counts[CONFIRMED]} confirmed violation(s), {counts[POTENTIAL]} potential, "
               f"{counts[MISSING]} missing-information, {counts[INCONCLUSIVE]} inconclusive, "
               f"{counts[COMPLIANT]} compliant. Status '{status}' means only that the checks that could run "
               "found these results. A procurement officer must review and decide.")
    if status == "no_issues_found":
        summary += " No issue was found by the checks that ran; this is not an approval."

    return {
        "overall_risk": risk, "compliance_status": status, "confidence": confidence, "score": score,
        "counts": counts, "summary": summary,
        "missing_info": [{"rule_code": f.rule_code, "title": f.title, "detail": f.explanation}
                         for f in findings if f.category == MISSING],
        "financial_risks": _financial_risks(ctx),
        "next_steps": _next_steps(findings, ctx),
    }


def _financial_risks(ctx: AssessmentContext) -> list[dict]:
    out: list[dict] = []
    r = ctx.request
    if r.total_amount is not None:
        out.append({"type": "exposure", "detail": f"Estimated commitment {r.total_amount:,.2f} {r.currency or '?'}"})
    for s in ctx.intake.get("splits", []):
        if s["code"] == "INT-SPLIT":
            out.append({"type": "split_purchase", "detail": f"Related requests combine to {s['combined_total']} USD, "
                                                            f"above the USD {s['threshold_usd']} threshold"})
    for i in ctx.intake.get("issues", []):
        if i["code"] == "INT-QUOTE-TOTAL":
            out.append({"type": "price_variance", "detail": i["message"]})
    if r.total_amount is not None:
        for q in ctx.quotes:
            adv = parse_terms(q.payment_terms).get("advance_pct")
            if adv and adv > 30:
                out.append({"type": "advance_payment", "detail":
                            f"{q.filename} proposes {adv}% paid in advance (about {r.total_amount * adv / 100:,.2f} "
                            f"{r.currency or ''} before delivery)"})
    return out


def _next_steps(findings: list[RuleFinding], ctx: AssessmentContext) -> list[dict]:
    steps: list[dict] = []
    r = ctx.request
    if r.total_amount is not None and r.currency == "USD":
        role, ref = approver_for(r.total_amount)
        steps.append({"action": f"Route to the {role} for the approval decision", "reason": "approval threshold",
                      "clause_ref": ref})
    for c in ctx.contracts:
        if c.total_value is not None and c.currency == "USD" and c.total_value > Decimal(10000):
            steps.append({"action": f"Obtain legal review of {c.filename} before signature",
                          "reason": "contract above USD 10,000", "clause_ref": "PRC-005:1.1"})
    verbs = {CONFIRMED: "Resolve", POTENTIAL: "Investigate", MISSING: "Obtain", INCONCLUSIVE: "Check manually"}
    for cat in (CONFIRMED, POTENTIAL, MISSING, INCONCLUSIVE):
        for f in findings:
            if f.category == cat:
                steps.append({"action": f"{verbs[cat]}: {f.title}", "reason": f.rule_code, "clause_ref": None})
    seen, unique = set(), []
    for s in steps:
        if s["action"] not in seen:
            seen.add(s["action"])
            unique.append(s)
    return unique
