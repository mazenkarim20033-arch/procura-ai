"""Duplicate and split-purchase detection. The decision logic is pure (operates on RequestView) so it
can be unit-tested and benchmarked without a database; `load_views` fetches rows for the API."""
from dataclasses import asdict, dataclass, field
from datetime import datetime
from decimal import Decimal

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import PurchaseRequest, RequestItem
from app.vendors.normalize import normalize_vendor_name

# Cosine-similarity thresholds on item-description embeddings. Defaults come from
# evals/runners/duplicates.py (see docs/BENCHMARKS.md); they are tied to the default embedding model.
SIMILAR_THRESHOLD = 0.80
OTHER_SUPPLIER_MARGIN = 0.05
SAME_SUPPLIER_WINDOW_DAYS = 90
OTHER_SUPPLIER_WINDOW_DAYS = 30
SPLIT_WINDOW_DAYS = 30  # PRC-006 clause 1.2
# Amount thresholds in USD appearing in PRC-001 / PRC-002 (approval bands and quotation bands).
THRESHOLDS_USD = [Decimal(x) for x in (1000, 5000, 10000, 25000, 50000)]
NEAR_THRESHOLD_RATIO = Decimal("0.85")


@dataclass
class RequestView:
    id: str
    request_no: str
    supplier_name: str | None
    currency: str | None
    total: Decimal | None
    category: str | None
    submitted_at: datetime
    fingerprint: str | None
    item_vectors: list[np.ndarray] = field(default_factory=list)


@dataclass
class DuplicateMatch:
    other_request_id: str
    other_request_no: str
    kind: str  # exact | similar | same_items_other_supplier | repeat_purchase (informational)
    score: float
    days_apart: int
    reasons: list[str]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class SplitFinding:
    code: str  # INT-SPLIT | INT-NEAR-THRESHOLD
    severity: str
    threshold_usd: str
    message: str
    related: list[dict] = field(default_factory=list)
    combined_total: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v)
    return v / n if n else v


def item_set_similarity(a: list[np.ndarray], b: list[np.ndarray]) -> float:
    """Symmetric soft overlap of two item sets: min of (mean best-match cosine a->b, b->a).
    Taking the min stops a big request from 'matching' a request that covers only one of its items."""
    if not a or not b:
        return 0.0
    ua, ub = np.stack([_unit(x) for x in a]), np.stack([_unit(x) for x in b])
    sims = ua @ ub.T
    return float(min(sims.max(axis=1).mean(), sims.max(axis=0).mean()))


def _days(a: datetime, b: datetime) -> int:
    return abs((a - b).days)


def classify_duplicates(
    target: RequestView, others: list[RequestView], *, sim_threshold: float = SIMILAR_THRESHOLD,
) -> list[DuplicateMatch]:
    out: list[DuplicateMatch] = []
    t_supplier = normalize_vendor_name(target.supplier_name)
    for o in others:
        if o.id == target.id:
            continue
        days = _days(target.submitted_at, o.submitted_at)
        if target.fingerprint and target.fingerprint == o.fingerprint:
            if days <= SAME_SUPPLIER_WINDOW_DAYS:
                out.append(DuplicateMatch(o.id, o.request_no, "exact", 1.0, days,
                                          ["identical supplier and identical items/quantities"]))
            else:
                # An identical order months later is usually a legitimate repeat purchase: informational.
                out.append(DuplicateMatch(o.id, o.request_no, "repeat_purchase", 1.0, days,
                                          [f"identical to a request {days} days apart (outside the "
                                           + f"{SAME_SUPPLIER_WINDOW_DAYS}-day duplicate window)"]))
            continue
        sim = item_set_similarity(target.item_vectors, o.item_vectors)
        same_supplier = bool(t_supplier) and t_supplier == normalize_vendor_name(o.supplier_name)
        if same_supplier and days <= SAME_SUPPLIER_WINDOW_DAYS and sim >= sim_threshold:
            out.append(DuplicateMatch(o.id, o.request_no, "similar", round(sim, 4), days,
                                      [f"same supplier, {days} days apart, item similarity {sim:.2f}"]))
        elif (not same_supplier and days <= OTHER_SUPPLIER_WINDOW_DAYS
              and sim >= sim_threshold + OTHER_SUPPLIER_MARGIN):
            out.append(DuplicateMatch(o.id, o.request_no, "same_items_other_supplier", round(sim, 4), days,
                                      [f"near-identical items, different supplier, {days} days apart"]))
    return sorted(out, key=lambda m: (-m.score, m.other_request_no))


def detect_splits(target: RequestView, others: list[RequestView]) -> list[SplitFinding]:
    """Flag (a) a group of same-supplier requests inside the policy window that individually stay under an
    amount threshold but together cross it, and (b) single requests priced just under a threshold.
    USD only: no FX source is configured, so other currencies are reported as a limitation, not guessed."""
    if target.total is None or target.currency != "USD":
        return []
    t_supplier = normalize_vendor_name(target.supplier_name)
    related = [
        o for o in others
        if o.id != target.id and o.total is not None and o.currency == "USD" and t_supplier
        and normalize_vendor_name(o.supplier_name) == t_supplier
        and _days(target.submitted_at, o.submitted_at) <= SPLIT_WINDOW_DAYS
        and not (target.category and o.category and target.category != o.category)
    ]
    findings: list[SplitFinding] = []
    group = [target, *related]
    combined = sum((g.total for g in group), Decimal(0))
    category_known = bool(target.category) and all(o.category for o in related)
    for t in THRESHOLDS_USD:
        if len(group) > 1 and all(g.total < t for g in group) and combined >= t:
            note = "" if category_known else " (category not recorded: matched on supplier and period only)"
            findings.append(SplitFinding(
                "INT-SPLIT", "warning", str(t),
                f"{len(group)} requests to the same supplier within {SPLIT_WINDOW_DAYS} days each stay below "
                f"USD {t:,.0f} but total USD {combined:,.2f}{note}",
                [{"request_no": g.request_no, "total": str(g.total)} for g in group], str(combined)))
            break
    for t in THRESHOLDS_USD:
        if t * NEAR_THRESHOLD_RATIO <= target.total < t:
            findings.append(SplitFinding(
                "INT-NEAR-THRESHOLD", "info", str(t),
                f"Total USD {target.total:,.2f} is within 15% below the USD {t:,.0f} threshold",
                [{"request_no": target.request_no, "total": str(target.total)}]))
            break
    return findings


def load_views(session: Session, *, exclude_status: tuple[str, ...] = ()) -> list[RequestView]:
    rows = session.execute(select(PurchaseRequest)).scalars().all()
    items = session.execute(select(RequestItem.request_id, RequestItem.item_embedding)).all()
    vecs: dict = {}
    for rid, emb in items:
        if emb is not None:
            vecs.setdefault(rid, []).append(np.asarray(emb, dtype=float))
    return [
        RequestView(
            id=str(r.id), request_no=r.request_no, supplier_name=r.supplier_name, currency=r.currency,
            total=r.total_amount, category=r.category, submitted_at=r.submitted_at,
            fingerprint=r.fingerprint, item_vectors=vecs.get(r.id, []),
        )
        for r in rows if r.status.value not in exclude_status
    ]
