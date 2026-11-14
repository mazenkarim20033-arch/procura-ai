"""Side-by-side comparison of supplier quotations for one request. Pure logic over QuoteQ objects.

Everything here is derived from the uploaded documents only. No market prices, supplier ratings or
registry data are consulted, and no exchange rates are applied: quotations in different currencies are
listed but not ranked against each other. Thresholds are heuristics, not policy values.
"""
import statistics
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import numpy as np

from app.rules.policy_rules import parse_terms
from app.vendors.normalize import normalize_item_description

BASIS = "Based only on the uploaded documents. No external supplier verification, market prices or exchange rates were used."
MATCH_SIM = 0.60           # cosine similarity (MiniLM) for the same item; F1 plateau 0.5-0.7 in evals/reports/item_alignment_*.json
OUTLIER_BAND = 0.25        # unit price more than 25% from the median of the vendors' prices
SUSPICIOUS_LOW = 0.60      # unit price below 60% of the median: possible scope gap or error
HISTORY_BAND = 0.30        # unit price moved more than 30% against the same vendor's earlier quotes
HISTORY_SIM = 0.70         # stricter end of that plateau: comparing the price of a different item is worse than missing one
TOKEN_SIM = 0.34           # fallback when no embeddings are available: word overlap (Jaccard) for the same checks
TOKEN_HISTORY_SIM = 0.5


@dataclass
class ItemQ:
    description: str
    quantity: Decimal | None
    unit_price: Decimal | None
    line_total: Decimal | None = None
    vec: np.ndarray | None = None


@dataclass
class QuoteQ:
    key: str  # vendor id (or normalised name) so repeated quotes from one vendor stay distinguishable
    vendor_name: str
    label: str  # file name or quote number
    currency: str | None
    total: Decimal | None
    subtotal: Decimal | None = None
    tax: Decimal | None = None
    delivery_days: int | None = None
    payment_terms: str | None = None
    issue_date: date | None = None
    valid_until: date | None = None
    items: list[ItemQ] = field(default_factory=list)
    issue_codes: list[str] = field(default_factory=list)


@dataclass
class HistoryPoint:
    vendor_key: str
    description: str
    unit_price: Decimal
    currency: str | None
    issue_date: date | None
    vec: np.ndarray | None = None


def _sim(a: ItemQ | HistoryPoint, b: ItemQ | HistoryPoint) -> tuple[float, bool]:
    """(similarity, used_embeddings). Cosine on embeddings when both items have them, else word overlap."""
    if a.vec is not None and b.vec is not None:
        na, nb = np.linalg.norm(a.vec), np.linalg.norm(b.vec)
        return (float(a.vec @ b.vec / (na * nb)) if na and nb else 0.0), True
    ta, tb = set(normalize_item_description(a.description).split()), set(normalize_item_description(b.description).split())
    return (len(ta & tb) / len(ta | tb) if ta | tb else 0.0), False


def _same_item(a, b, embed_threshold: float, token_threshold: float) -> tuple[bool, float]:
    score, used_vec = _sim(a, b)
    return score >= (embed_threshold if used_vec else token_threshold), score


def _flag(code: str, severity: str, message: str, **extra) -> dict:
    return {"code": code, "severity": severity, "message": message, **extra}


def _align(quotes: list[QuoteQ], threshold: float) -> list[dict]:
    """Rows keyed by the anchor quote with the most items; each other quote's items are matched one-to-one."""
    anchor = max(quotes, key=lambda q: len(q.items))
    rows = [{"description": it.description, "cells": {anchor.label: it}} for it in anchor.items]
    for q in quotes:
        if q is anchor:
            continue
        # A row's reference item is the first one placed in it (rows created from unmatched items have no anchor cell).
        pairs = []
        for ri, row in enumerate(rows):
            ref = next(iter(row["cells"].values()))
            for ii, it in enumerate(q.items):
                ok, score = _same_item(ref, it, threshold, TOKEN_SIM)
                if ok:
                    pairs.append((score, ri, ii))
        used_rows, used_items = set(), set()
        for _score, ri, ii in sorted(pairs, reverse=True):
            if ri in used_rows or ii in used_items:
                continue
            rows[ri]["cells"][q.label] = q.items[ii]
            used_rows.add(ri)
            used_items.add(ii)
        for ii, it in enumerate(q.items):  # items no anchor row matched become their own rows
            if ii not in used_items:
                rows.append({"description": it.description, "cells": {q.label: it}})
    return rows


def compare_quotes(quotes: list[QuoteQ], request_date: date | None, *, request_currency: str | None = None,
                   history: list[HistoryPoint] | None = None, match_threshold: float = MATCH_SIM) -> dict:
    out: dict = {"basis": BASIS, "quotes": [], "item_rows": [], "ranking": [], "flags": [], "notes": [],
                 "parameters": {"match_similarity": match_threshold, "outlier_band": OUTLIER_BAND,
                                "suspiciously_low_ratio": SUSPICIOUS_LOW, "history_band": HISTORY_BAND}}
    if not quotes:
        out["notes"].append("No quotations attached to compare.")
        return out
    currencies = [q.currency for q in quotes if q.currency]
    currency = request_currency or (max(set(currencies), key=currencies.count) if currencies else None)
    out["currency"] = currency
    comparable = [q for q in quotes if q.currency == currency]
    for q in quotes:
        if q.currency != currency:
            out["flags"].append(_flag("CMP-CURRENCY", "warning",
                                      f"{q.label} is in {q.currency or 'an unknown currency'}, not {currency}: listed but not ranked (no exchange-rate source)",
                                      vendor=q.vendor_name))

    for q in quotes:
        terms = parse_terms(q.payment_terms)
        out["quotes"].append({
            "label": q.label, "vendor": q.vendor_name, "currency": q.currency,
            "total": None if q.total is None else str(q.total), "subtotal": None if q.subtotal is None else str(q.subtotal),
            "tax": None if q.tax is None else str(q.tax), "delivery_days": q.delivery_days,
            "payment_terms": q.payment_terms, "net_days": terms.get("net_days"),
            "advance_pct": None if "advance_pct" not in terms else str(terms["advance_pct"]),
            "validity_days_from_request": (q.valid_until - request_date).days if q.valid_until and request_date else None,
            "valid_until": q.valid_until.isoformat() if q.valid_until else None,
        })
        bad = [c for c in q.issue_codes if c.endswith("_mismatch")]
        if bad:
            out["flags"].append(_flag("CMP-ARITHMETIC", "warning", f"{q.label} has arithmetic errors ({', '.join(bad)}); its prices are unreliable",
                                      vendor=q.vendor_name))
        if q.valid_until is None:
            out["flags"].append(_flag("CMP-NO-VALIDITY", "info", f"{q.label} states no validity date", vendor=q.vendor_name))
        elif request_date and (q.valid_until - request_date).days < 0:
            out["flags"].append(_flag("CMP-EXPIRED", "warning", f"{q.label} expired before the request date", vendor=q.vendor_name))

    # ---- totals: rank only quotations in the same currency; tax treatment can make totals incomparable
    taxed = {q.label for q in comparable if q.tax and q.tax > 0}
    mixed_tax = bool(taxed) and len(taxed) != len(comparable)
    basis_field = "subtotal" if mixed_tax else "total"
    if mixed_tax:
        out["notes"].append("Some quotations include tax and others do not, so ranking uses subtotals (before tax).")
    ranked = sorted((q for q in comparable if getattr(q, basis_field) is not None), key=lambda q: getattr(q, basis_field))
    out["ranking"] = [{"rank": i + 1, "label": q.label, "vendor": q.vendor_name, basis_field: str(getattr(q, basis_field))}
                      for i, q in enumerate(ranked)]
    if len(ranked) >= 2:
        low, high = getattr(ranked[0], basis_field), getattr(ranked[-1], basis_field)
        if low > 0:
            out["notes"].append(f"Spread between lowest and highest {basis_field}: {(high - low) / low:.0%}.")
    if len(comparable) < 2:
        out["notes"].append("Fewer than two quotations in a comparable currency; no price comparison possible.")

    # ---- item-level prices
    if len(comparable) >= 2:
        rows = _align(comparable, match_threshold)
        for row in rows:
            cells = row["cells"]
            priced = {label: it for label, it in cells.items() if it.unit_price is not None}
            entry = {"description": row["description"],
                     "cells": {label: {"quantity": None if it.quantity is None else str(it.quantity),
                                       "unit_price": None if it.unit_price is None else str(it.unit_price),
                                       "description": it.description} for label, it in cells.items()}}
            missing = [q.label for q in comparable if q.label not in cells]
            if missing and len(cells) >= 1 and len(comparable) >= 2:
                out["flags"].append(_flag("CMP-MISSING-ITEM", "info", f"'{row['description']}' is not in: {', '.join(missing)}",
                                          item=row["description"]))
            qtys = {it.quantity for it in cells.values() if it.quantity is not None}
            if len(qtys) > 1:
                out["flags"].append(_flag("CMP-QTY-DIFFERS", "info", f"Quantities differ across quotations for '{row['description']}'",
                                          item=row["description"]))
            if len(priced) >= 2:
                med = statistics.median(float(it.unit_price) for it in priced.values())
                entry["median_unit_price"] = round(med, 4)
                for label, it in priced.items():
                    ratio = float(it.unit_price) / med if med else 1.0
                    entry["cells"][label]["ratio_to_median"] = round(ratio, 3)
                    vendor = next(q.vendor_name for q in comparable if q.label == label)
                    if len(priced) >= 3 and ratio < SUSPICIOUS_LOW:
                        out["flags"].append(_flag("CMP-SUSPICIOUSLY-LOW", "warning",
                                                  f"{label}: '{row['description']}' at {it.unit_price} is {1 - ratio:.0%} below the median {med:.2f}; check scope or errors",
                                                  vendor=vendor, item=row["description"]))
                    elif abs(ratio - 1) > OUTLIER_BAND and len(priced) >= 3:
                        out["flags"].append(_flag("CMP-PRICE-OUTLIER", "warning",
                                                  f"{label}: '{row['description']}' at {it.unit_price} is {abs(ratio - 1):.0%} {'above' if ratio > 1 else 'below'} the median {med:.2f}",
                                                  vendor=vendor, item=row["description"]))
                if len(priced) == 2:
                    a, b = list(priced.values())
                    hi, lo = max(a.unit_price, b.unit_price), min(a.unit_price, b.unit_price)
                    if lo > 0 and (hi - lo) / lo > OUTLIER_BAND:
                        out["flags"].append(_flag("CMP-PRICE-GAP", "info",
                                                  f"'{row['description']}': the two quotations differ by {(hi - lo) / lo:.0%}", item=row["description"]))
            out["item_rows"].append(entry)

    # ---- the same vendor's earlier prices
    for q in quotes:
        for it in q.items:
            if it.unit_price is None:
                continue
            past = [h for h in (history or []) if h.vendor_key == q.key and h.currency == q.currency
                    and _same_item(it, h, HISTORY_SIM, TOKEN_HISTORY_SIM)[0]
                    and (not h.issue_date or not q.issue_date or h.issue_date < q.issue_date)]
            if past:
                med = statistics.median(float(h.unit_price) for h in past)
                if med and abs(float(it.unit_price) - med) / med > HISTORY_BAND:
                    out["flags"].append(_flag("CMP-HISTORY", "warning",
                                              f"{q.vendor_name}: '{it.description}' at {it.unit_price} vs {med:.2f} on {len(past)} earlier quotation(s) ({(float(it.unit_price) - med) / med:+.0%})",
                                              vendor=q.vendor_name, item=it.description))
    order = {"warning": 0, "info": 1}
    out["flags"].sort(key=lambda f: (order.get(f["severity"], 2), f["code"]))
    return out
