"""Deterministic policy rules. Each rule implements specific clauses of the synthetic policies and cites
them by looking the clause up in the corpus; if a needed clause is not loaded, the finding degrades to
INCONCLUSIVE instead of citing text that was never seen.

Category semantics (see docs/PRD.md FR-D):
  confirmed_violation  a fact established inside the submitted file contradicts a clause
  potential_violation  something suspicious that a human must investigate
  missing_information  the file lacks what a clause needs; compliance cannot be judged (NOT a violation)
  compliant            a clause clearly applies and is satisfied
  inconclusive         the check could not be run
"""
import re
from dataclasses import dataclass, field
from decimal import Decimal

from app.ai.guards.injection import scan
from app.ai.pipeline.context import AssessmentContext, Clause, PolicyCorpus
from app.vendors.normalize import normalize_vendor_name

CONFIRMED, POTENTIAL, MISSING, COMPLIANT, INCONCLUSIVE = (
    "confirmed_violation", "potential_violation", "missing_information", "compliant", "inconclusive")
SEVERITY = {CONFIRMED: "high", POTENTIAL: "medium", MISSING: "medium", INCONCLUSIVE: "low", COMPLIANT: None}

# Clauses that deterministic rules own. The LLM stage is only shown clauses outside this set.
RULE_CLAUSES = {
    "PRC-001:1.3", "PRC-001:2.1", "PRC-001:2.2", "PRC-001:2.3", "PRC-001:2.4",
    "PRC-002:1.1", "PRC-002:1.2", "PRC-002:1.3", "PRC-002:1.4", "PRC-002:2.1", "PRC-002:2.2", "PRC-002:2.3",
    "PRC-003:1.1", "PRC-003:3.1", "PRC-003:3.2",
    "PRC-005:2.1", "PRC-005:2.2", "PRC-005:2.3",
    "PRC-006:1.1", "PRC-006:1.2", "PRC-006:2.1", "PRC-006:4.1",
}
QUOTE_BANDS = [(Decimal(1000), 0), (Decimal(5000), 1), (Decimal(25000), 3)]  # PRC-002 1.1-1.3
APPROVERS = [(Decimal(1000), "department manager", "PRC-001:2.1"), (Decimal(10000), "procurement officer", "PRC-001:2.2"),
             (Decimal(50000), "finance director", "PRC-001:2.3")]
APPROVER_TOP = ("chief financial officer", "PRC-001:2.4")


@dataclass
class Evidence:
    kind: str  # policy_chunk | request_field | document_span | quotation
    quote: str | None = None
    chunk_id: str | None = None
    clause_ref: str | None = None
    ref: dict = field(default_factory=dict)


@dataclass
class RuleFinding:
    rule_code: str
    category: str
    title: str
    explanation: str
    evidence: list[Evidence]
    severity: str | None = None
    confidence: float | None = None
    source: str = "rule"  # rule | llm


def approver_for(amount: Decimal) -> tuple[str, str]:
    for limit, role, ref in APPROVERS:
        if amount <= limit:
            return role, ref
    return APPROVER_TOP


def required_quotes(amount: Decimal) -> int | str:
    for limit, n in QUOTE_BANDS:
        if amount <= limit:
            return n
    return "tender"


def parse_terms(text: str | None) -> dict:
    out: dict = {}
    if not text:
        return out
    if m := re.search(r"net\s*(\d+)", text, re.IGNORECASE):
        out["net_days"] = int(m.group(1))
    if m := re.search(r"(\d+(?:\.\d+)?)\s*%\s*(?:advance|upfront|deposit|prepay|prepayment)", text, re.IGNORECASE):
        out["advance_pct"] = Decimal(m.group(1))
    return out


class _Run:
    def __init__(self, ctx: AssessmentContext, corpus: PolicyCorpus):
        self.ctx, self.corpus = ctx, corpus
        self.findings: list[RuleFinding] = []
        self.ran: set[str] = set()

    def clause(self, ref: str) -> Clause | None:
        return self.corpus.get(ref)

    def emit(self, code: str, category: str, title: str, explanation: str, clause_refs: list[str],
             evidence: list[Evidence], confidence: float | None = None) -> None:
        ev = list(evidence)
        for ref in clause_refs:
            c = self.clause(ref)
            if c is None:
                # Cannot cite the policy text => never assert a verdict from it.
                self.findings.append(RuleFinding(
                    code, INCONCLUSIVE, f"{title} (policy clause not loaded)",
                    f"Rule {code} needs clause {ref}, which is not available in the policy corpus, so no verdict "
                    f"was made. Original observation: {explanation}", ev, SEVERITY[INCONCLUSIVE], confidence))
                return
            ev.append(Evidence("policy_chunk", c.text, c.chunk_id, ref))
        self.findings.append(RuleFinding(code, category, title, explanation, ev, SEVERITY[category], confidence))


def _req(field_name: str, value) -> Evidence:
    return Evidence("request_field", None, None, None, {"field": field_name, "value": None if value is None else str(value)})


def _quote_ev(q) -> Evidence:
    return Evidence("quotation", None, None, None, {"document_id": q.document_id, "filename": q.filename})


def evaluate_rules(ctx: AssessmentContext, corpus: PolicyCorpus) -> tuple[list[RuleFinding], set[str]]:
    r = _Run(ctx, corpus)
    req = ctx.request
    quotes = ctx.quotes
    amount = req.total_amount if req.currency == "USD" and req.total_amount is not None else None

    # ---- amount availability (gates the amount-based rules)
    if amount is None:
        if req.total_amount is None:
            r.emit("R-AMOUNT", MISSING, "Estimated total missing",
                   "Without an estimated total, approval level, quotation count and approved-supplier rules cannot "
                   "be evaluated.", [], [_req("total_amount", None)])
        else:
            r.emit("R-AMOUNT", INCONCLUSIVE, "Amount rules need a USD total",
                   f"The request is in {req.currency}. The policy states limits in USD and converts at the treasury "
                   "rate on the request date; no exchange-rate source is configured, so amount-based rules were "
                   "not evaluated.", ["PRC-001:1.3"], [_req("currency", req.currency), _req("total_amount", req.total_amount)])
    else:
        # ---- PRC-002 1.x: number of quotations
        distinct = {normalize_vendor_name(q.vendor_name) for q in quotes if q.vendor_name}
        need = required_quotes(amount)
        band_ref = {0: "PRC-002:1.1", 1: "PRC-002:1.2", 3: "PRC-002:1.3", "tender": "PRC-002:1.4"}[need]
        ev = [_req("total_amount", amount), *[_quote_ev(q) for q in quotes]]
        r.ran.add("R-QUOTE-COUNT")
        if need == "tender":
            r.emit("R-QUOTE-COUNT", MISSING, "Formal tender evidence not available",
                   f"A purchase of USD {amount:,.2f} must be run as a formal tender; no tender documentation can be "
                   "recognised in the submitted files.", [band_ref], ev)
        elif need == 0 or len(distinct) >= need:
            r.emit("R-QUOTE-COUNT", COMPLIANT, "Quotation requirement met",
                   f"USD {amount:,.2f} needs {need} written quotation(s); {len(distinct)} distinct supplier(s) attached.",
                   [band_ref], ev)
        else:
            r.emit("R-QUOTE-COUNT", MISSING, "Not enough quotations attached",
                   f"USD {amount:,.2f} needs at least {need} written quotation(s) from different suppliers; "
                   f"{len(distinct)} distinct supplier(s) attached. The policy may have been followed with "
                   "quotations that were not uploaded.", [band_ref], ev)

        # ---- PRC-003 1.1: approved supplier list
        if amount > Decimal(5000) and req.supplier_name:
            r.ran.add("R-SUPPLIER-APPROVED")
            if ctx.approved_suppliers is None:
                r.emit("R-SUPPLIER-APPROVED", MISSING, "Approved supplier list not available",
                       "Purchases above USD 5,000 must use an approved supplier, but no approved-supplier list is "
                       "configured, so this cannot be checked.", ["PRC-003:1.1"], [_req("supplier_name", req.supplier_name)])
            else:
                approved = {normalize_vendor_name(s) for s in ctx.approved_suppliers}
                if normalize_vendor_name(req.supplier_name) in approved:
                    r.emit("R-SUPPLIER-APPROVED", COMPLIANT, "Supplier is on the approved list",
                           f"'{req.supplier_name}' matches an approved supplier.", ["PRC-003:1.1"],
                           [_req("supplier_name", req.supplier_name), _req("total_amount", amount)])
                else:
                    r.emit("R-SUPPLIER-APPROVED", CONFIRMED, "Supplier is not on the approved list",
                           f"USD {amount:,.2f} exceeds USD 5,000 and '{req.supplier_name}' is not on the configured "
                           "approved supplier list.", ["PRC-003:1.1"],
                           [_req("supplier_name", req.supplier_name), _req("total_amount", amount)])

    # ---- PRC-002 2.1: quotation validity (relative to the request date)
    if req.submitted_on and quotes:
        short = [q for q in quotes if q.valid_until and (q.valid_until - req.submitted_on).days < 30]
        nodate = [q for q in quotes if q.valid_until is None]
        r.ran.add("R-QUOTE-VALIDITY")
        if short:
            r.emit("R-QUOTE-VALIDITY", CONFIRMED, "Quotation valid for less than 30 days",
                   "; ".join(f"{q.filename}: valid until {q.valid_until}, {(q.valid_until - req.submitted_on).days} days "
                             f"after the request date {req.submitted_on}" for q in short),
                   ["PRC-002:2.1"], [_req("submitted_on", req.submitted_on), *[_quote_ev(q) for q in short]])
        if nodate:
            r.emit("R-QUOTE-VALIDITY-MISSING", MISSING, "Quotation has no validity date",
                   "Validity cannot be checked for: " + ", ".join(q.filename for q in nodate),
                   ["PRC-002:2.1"], [_quote_ev(q) for q in nodate])
        if not short and not nodate:
            r.emit("R-QUOTE-VALIDITY", COMPLIANT, "Quotation validity is sufficient",
                   "All attached quotations stay valid at least 30 days from the request date.",
                   ["PRC-002:2.1"], [_req("submitted_on", req.submitted_on), *[_quote_ev(q) for q in quotes]])

    # ---- PRC-002 2.2 / 2.3: quotation content and arithmetic
    content_fields = {"vendor_name", "quote_no", "currency", "items"}
    bad_content = [q for q in quotes if any(c.split(":")[0] in {"missing_field", "invalid_value"}
                                            and c.split(":", 1)[-1].split(".")[0] in content_fields for c in q.issue_codes)]
    bad_math = [q for q in quotes if any(c in {"line_total_mismatch", "subtotal_mismatch", "total_mismatch"}
                                         for c in q.issue_codes)]
    if bad_content:
        r.emit("R-QUOTE-CONTENT", CONFIRMED, "Quotation lacks required content",
               "Missing or invalid supplier name, quotation number, itemised prices or currency in: "
               + ", ".join(q.filename for q in bad_content), ["PRC-002:2.2"], [_quote_ev(q) for q in bad_content])
    if bad_math:
        r.emit("R-QUOTE-ARITHMETIC", CONFIRMED, "Quotation contains arithmetic errors",
               "Totals do not add up in: " + ", ".join(q.filename for q in bad_math)
               + ". The supplier must correct them before the quotation can be used.", ["PRC-002:2.3"],
               [_quote_ev(q) for q in bad_math])

    # ---- PRC-003 3.1 / 3.2: supplier identification and name consistency
    if not (req.supplier_name or "").strip():
        r.emit("R-SUPPLIER-NAME", MISSING, "Supplier not identified",
               "The request does not name a supplier.", ["PRC-003:3.1"], [_req("supplier_name", None)])
    else:
        mismatch = [i for i in ctx.intake.get("issues", []) if i["code"] == "INT-QUOTE-SUPPLIER"]
        if mismatch:
            r.emit("R-SUPPLIER-NAME", POTENTIAL, "Supplier name differs from quotations",
                   mismatch[0]["message"], ["PRC-003:3.2"], [_req("supplier_name", req.supplier_name),
                                                             *[_quote_ev(q) for q in quotes]])
        elif quotes:
            r.ran.add("R-SUPPLIER-NAME")
            r.emit("R-SUPPLIER-NAME", COMPLIANT, "Supplier name matches a quotation",
                   f"'{req.supplier_name}' matches an attached quotation.", ["PRC-003:3.2"],
                   [_req("supplier_name", req.supplier_name)])

    # ---- PRC-006 2.1: justification present (adequacy is a judgement, left to the LLM stage and the human)
    r.ran.add("R-JUSTIFICATION")
    if not (req.justification or "").strip():
        r.emit("R-JUSTIFICATION", CONFIRMED, "Business justification missing",
               "Every purchase request must include a business justification; this one has none.",
               ["PRC-006:2.1"], [_req("justification", None)])
    else:
        r.emit("R-JUSTIFICATION", COMPLIANT, "Business justification present",
               "A justification is provided (its adequacy is left to the reviewer).", ["PRC-006:2.1"],
               [_req("justification", req.justification)])

    # ---- PRC-006 1.x / 4.1: split purchases and duplicates (from intake)
    for s in ctx.intake.get("splits", []):
        if s["code"] == "INT-SPLIT":
            r.emit("R-SPLIT", POTENTIAL, "Possible split purchase", s["message"], ["PRC-006:1.1", "PRC-006:1.2"],
                   [_req("total_amount", req.total_amount),
                    Evidence("request_field", None, None, None, {"field": "related_requests", "value": s["related"]})])
    for d in ctx.intake.get("duplicates", []):
        if d["kind"] in {"exact", "similar"}:
            r.emit("R-DUPLICATE", POTENTIAL, f"Possible duplicate of {d['other_request_no']}",
                   "; ".join(d["reasons"]), ["PRC-006:4.1"],
                   [Evidence("request_field", None, None, None, {"field": "duplicate_of", "value": d["other_request_no"]})])

    # ---- PRC-005 2.x: payment terms in contracts (confirmed) and quotations (proposals: potential)
    for doc, is_contract in [*[(c, True) for c in ctx.contracts], *[(q, False) for q in quotes]]:
        terms = parse_terms(doc.payment_terms)
        ev = [Evidence("quotation" if not is_contract else "document_span", doc.payment_terms, None, None,
                       {"document_id": doc.document_id, "filename": doc.filename})]
        kind = CONFIRMED if is_contract else POTENTIAL
        what = "contract" if is_contract else "quotation (proposed terms)"
        if "net_days" in terms and terms["net_days"] < 30:
            r.emit("R-PAYMENT-TERMS", kind, "Payment term shorter than net 30",
                   f"{what} {doc.filename} states net {terms['net_days']} days; the minimum is net 30.", ["PRC-005:2.1"], ev)
        if "net_days" in terms and terms["net_days"] > 60:
            r.emit("R-PAYMENT-TERMS", POTENTIAL, "Payment term longer than net 60 needs approval",
                   f"{what} {doc.filename} states net {terms['net_days']} days; terms beyond net 60 need finance "
                   "director approval.", ["PRC-005:2.2"], ev)
        if "advance_pct" in terms and terms["advance_pct"] > 30:
            r.emit("R-ADVANCE-PAYMENT", kind, "Advance payment above 30 percent",
                   f"{what} {doc.filename} asks for {terms['advance_pct']}% in advance; the limit is 30 percent.",
                   ["PRC-005:2.3"], ev)

    # ---- instruction-like text in submitted data (guard, not a policy clause)
    for hit in scan([("justification", req.justification),
                     *[(f"item {i + 1} description", it.description) for i, it in enumerate(req.items)],
                     *ctx.untrusted_text]):
        r.findings.append(RuleFinding(
            "GUARD-INJECTION", POTENTIAL, f"Instruction-like text in {hit.source}",
            "Text that tries to instruct an automated system was found in submitted data. It was not followed and "
            "was excluded from any decision; a reviewer should check the document's origin.",
            [Evidence("request_field" if "justification" in hit.source or "item" in hit.source else "document_span",
                      hit.snippet, None, None, {"source": hit.source, "pattern": hit.pattern_id})], SEVERITY[POTENTIAL]))
    return r.findings, r.ran
