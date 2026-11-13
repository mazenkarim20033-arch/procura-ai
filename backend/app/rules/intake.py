"""Deterministic intake checks on a purchase request: missing information and internal/quote
inconsistencies. No LLM, no policy interpretation (policy rules arrive with the compliance engine)."""
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from app.vendors.normalize import compare_vendor_names

TOLERANCE = Decimal("0.01")
QUOTE_TOTAL_VARIANCE = Decimal("0.15")  # heuristic flag threshold, not a policy value


@dataclass
class ItemSnapshot:
    description: str | None
    quantity: Decimal | None
    unit_cost: Decimal | None
    line_total: Decimal | None


@dataclass
class RequestSnapshot:
    request_no: str | None
    requester_name: str | None
    department: str | None
    currency: str | None
    supplier_name: str | None
    justification: str | None
    total_amount: Decimal | None
    submitted_on: date | None
    items: list[ItemSnapshot] = field(default_factory=list)


@dataclass
class QuoteSnapshot:
    document_id: str
    filename: str
    vendor_name: str | None
    currency: str | None
    total: Decimal | None
    issue_date: date | None
    valid_until: date | None
    quote_no: str | None = None


@dataclass
class IntakeIssue:
    code: str
    kind: str  # missing | inconsistent | limitation
    severity: str  # error | warning | info
    field: str
    message: str
    evidence: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return asdict(self)


def _blank(v) -> bool:
    return v is None or (isinstance(v, str) and not v.strip())


def check_request(req: RequestSnapshot, quotes: list[QuoteSnapshot]) -> list[IntakeIssue]:
    out: list[IntakeIssue] = []

    def missing(fname: str, label: str, severity: str = "error") -> None:
        out.append(IntakeIssue(f"INT-MISSING-{fname.upper()}", "missing", severity, fname,
                               f"{label} is missing"))

    for fname, label in [("requester_name", "Requester"), ("department", "Department"),
                         ("currency", "Currency"), ("supplier_name", "Supplier"),
                         ("justification", "Business justification"), ("total_amount", "Estimated total")]:
        if _blank(getattr(req, fname)):
            missing(fname, label)
    if not req.items:
        missing("items", "Requested items")
    for i, it in enumerate(req.items):
        if _blank(it.description):
            missing(f"items.{i}.description", f"Item {i + 1} description")
        if it.quantity is None or it.quantity <= 0:
            missing(f"items.{i}.quantity", f"Item {i + 1} quantity")
        if it.unit_cost is None:
            missing(f"items.{i}.unit_cost", f"Item {i + 1} unit cost")
    if not quotes:
        out.append(IntakeIssue("INT-NO-QUOTATION", "missing", "info", "documents",
                               "No supplier quotation is attached to this request"))

    # --- internal consistency
    if req.currency and not (len(req.currency) == 3 and req.currency.isalpha() and req.currency.isupper()):
        out.append(IntakeIssue("INT-BAD-CURRENCY", "inconsistent", "error", "currency",
                               f"'{req.currency}' is not a 3-letter ISO currency code"))
    line_sum = Decimal(0)
    complete_lines = True
    for i, it in enumerate(req.items):
        if it.line_total is None:
            complete_lines = False
            continue
        line_sum += it.line_total
        if it.quantity is not None and it.unit_cost is not None:
            expected = it.quantity * it.unit_cost
            if abs(expected - it.line_total) > TOLERANCE:
                out.append(IntakeIssue(
                    "INT-LINE-TOTAL", "inconsistent", "error", f"items.{i}.line_total",
                    f"{it.quantity} x {it.unit_cost} = {expected:.2f} but the line total is {it.line_total}",
                    {"expected": str(expected), "stated": str(it.line_total)}))
    if req.items and complete_lines and req.total_amount is not None and abs(line_sum - req.total_amount) > TOLERANCE:
        out.append(IntakeIssue(
            "INT-TOTAL", "inconsistent", "error", "total_amount",
            f"Line totals sum to {line_sum:.2f} but the estimated total is {req.total_amount}",
            {"line_sum": str(line_sum), "stated": str(req.total_amount)}))

    # --- request versus attached quotations
    # Competing quotations from other vendors are normal; only warn when NONE of them comes from the
    # supplier named on the request (or the only close match looks like a misspelling).
    if quotes and not _blank(req.supplier_name):
        matches = {q.document_id: compare_vendor_names(req.supplier_name, q.vendor_name) for q in quotes}
        if "same" not in matches.values():
            similar = [q for q in quotes if matches[q.document_id] == "similar"]
            out.append(IntakeIssue(
                "INT-QUOTE-SUPPLIER", "inconsistent", "warning", "supplier_name",
                f"No attached quotation is from the requested supplier '{req.supplier_name}'"
                + (f"; '{similar[0].vendor_name}' is a near match, check spelling" if similar else ""),
                {"quotation_vendors": sorted({q.vendor_name or "?" for q in quotes}),
                 "near_match": bool(similar)}))
    for q in quotes:
        ev = {"quotation": q.filename, "document_id": q.document_id}
        if req.currency and q.currency and req.currency != q.currency:
            out.append(IntakeIssue(
                "INT-QUOTE-CURRENCY", "inconsistent", "warning", "currency",
                f"Request currency {req.currency} differs from quotation currency {q.currency}", ev))
        same_supplier = compare_vendor_names(req.supplier_name, q.vendor_name) == "same"
        if (same_supplier and req.total_amount and q.total is not None and q.currency == req.currency
                and req.total_amount > 0):
            variance = abs(q.total - req.total_amount) / req.total_amount
            if variance > QUOTE_TOTAL_VARIANCE:
                out.append(IntakeIssue(
                    "INT-QUOTE-TOTAL", "inconsistent", "warning", "total_amount",
                    f"Quotation total {q.total} differs from the estimated total {req.total_amount} "
                    f"by {variance:.0%}", {**ev, "variance": f"{variance:.4f}"}))
        if req.submitted_on:
            if q.valid_until and q.valid_until < req.submitted_on:
                out.append(IntakeIssue(
                    "INT-QUOTE-EXPIRED", "inconsistent", "error", "documents",
                    f"Quotation expired on {q.valid_until} before the request date {req.submitted_on}", ev))
            if q.issue_date and q.issue_date > req.submitted_on:
                out.append(IntakeIssue(
                    "INT-QUOTE-DATE", "inconsistent", "warning", "documents",
                    f"Quotation is dated {q.issue_date}, after the request date {req.submitted_on}", ev))
    return out
