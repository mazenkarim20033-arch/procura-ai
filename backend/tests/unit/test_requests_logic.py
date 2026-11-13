from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

import numpy as np

from app.rules.intake import ItemSnapshot, QuoteSnapshot, RequestSnapshot, check_request
from app.services.duplicates import (
    RequestView,
    classify_duplicates,
    detect_splits,
    item_set_similarity,
)
from app.vendors.normalize import (
    compare_vendor_names,
    normalize_vendor_name,
    request_fingerprint,
)

D = Decimal


def snap(**kw) -> RequestSnapshot:
    base = dict(
        request_no="PR-1", requester_name="Layla", department="Finance", currency="USD",
        supplier_name="Orion Tech Supplies Ltd.", justification="Replacement laptops", total_amount=D("2000.00"),
        submitted_on=date(2026, 3, 10),
        items=[ItemSnapshot("Laptop", D(2), D("1000.00"), D("2000.00"))],
    )
    base.update(kw)
    return RequestSnapshot(**base)


def quote(**kw) -> QuoteSnapshot:
    base = dict(document_id="d1", filename="q.pdf", vendor_name="Orion Tech Supplies Ltd.", currency="USD",
                total=D("2000.00"), issue_date=date(2026, 3, 1), valid_until=date(2026, 4, 15))
    base.update(kw)
    return QuoteSnapshot(**base)


def codes(issues) -> set[str]:
    return {i.code for i in issues}


# ------------------------------------------------------------------ names & fingerprint
def test_vendor_name_normalisation_handles_suffix_spelling_and_punctuation():
    assert normalize_vendor_name("Orion Tech Supplies Ltd.") == normalize_vendor_name("ORION TECH SUPPLIES LIMITED")
    assert normalize_vendor_name("Delta Office Furniture LLC") == normalize_vendor_name("Delta Office Furniture L.L.C.")
    assert normalize_vendor_name("Cairo Print & Packaging Co.") == "cairo print and packaging"
    assert normalize_vendor_name("Summit Networks Inc.") == normalize_vendor_name("Summit Networks Incorporated")
    assert normalize_vendor_name("Limited") == "limited"  # a name that is only a suffix is kept
    assert normalize_vendor_name(None) == ""


def test_vendor_comparison_levels():
    assert compare_vendor_names("Orion Tech Ltd", "orion tech limited") == "same"
    assert compare_vendor_names("Orion Tech Supplies", "Orion Tech Suplies") == "similar"
    assert compare_vendor_names("Orion Tech Supplies", "Nile Cloud Services") == "different"
    assert compare_vendor_names("Orion", None) == "unknown"


def test_fingerprint_ignores_order_case_and_suffix_but_not_quantity():
    a = request_fingerprint("Orion Tech Ltd.", [("Laptop 14in", D(2)), ("Dock USB-C", D(5))])
    b = request_fingerprint("ORION TECH LIMITED", [("dock usb-c", D("5.0")), ("LAPTOP 14IN", D(2))])
    c = request_fingerprint("Orion Tech Ltd.", [("Laptop 14in", D(3)), ("Dock USB-C", D(5))])
    assert a == b and a != c


# ------------------------------------------------------------------ intake checks
def test_clean_request_with_matching_quote_has_no_issues():
    assert check_request(snap(), [quote()]) == []


def test_missing_information_is_listed_per_field():
    s = snap(requester_name=None, department=" ", justification=None, supplier_name=None, total_amount=None,
             items=[ItemSnapshot("Laptop", None, None, None)])
    got = codes(check_request(s, [quote()]))
    assert {"INT-MISSING-REQUESTER_NAME", "INT-MISSING-DEPARTMENT", "INT-MISSING-JUSTIFICATION",
            "INT-MISSING-SUPPLIER_NAME", "INT-MISSING-TOTAL_AMOUNT", "INT-MISSING-ITEMS.0.QUANTITY",
            "INT-MISSING-ITEMS.0.UNIT_COST"} <= got
    assert "INT-MISSING-ITEMS" in codes(check_request(snap(items=[]), []))


def test_no_quotation_is_informational_only():
    issues = check_request(snap(), [])
    assert [(i.code, i.severity) for i in issues] == [("INT-NO-QUOTATION", "info")]


def test_arithmetic_inconsistencies_are_flagged_not_corrected():
    s = snap(total_amount=D("2500.00"), items=[ItemSnapshot("Laptop", D(2), D("1000.00"), D("1900.00"))])
    got = codes(check_request(s, []))
    assert {"INT-LINE-TOTAL", "INT-TOTAL"} <= got
    assert "INT-BAD-CURRENCY" in codes(check_request(snap(currency="usd"), []))


def test_quote_comparison_flags():
    issues = check_request(snap(), [quote(currency="EUR")])
    assert "INT-QUOTE-CURRENCY" in codes(issues)

    issues = check_request(snap(), [quote(vendor_name="Nile Cloud Services")])
    assert "INT-QUOTE-SUPPLIER" in codes(issues)
    # competing quotes are normal: no warning while at least one quote is from the requested supplier
    assert check_request(snap(), [quote(vendor_name="Nile Cloud Services", document_id="d2"), quote()]) == []
    near = check_request(snap(), [quote(vendor_name="Orion Tech Suplies Ltd.")])
    assert "near match" in next(i for i in near if i.code == "INT-QUOTE-SUPPLIER").message
    # the vendor-spelling variants produced by the synthetic generator must NOT be flagged
    assert check_request(snap(), [quote(vendor_name="ORION TECH SUPPLIES LIMITED")]) == []

    issues = check_request(snap(), [quote(total=D("2600.00"))])  # 30% above the estimate
    assert "INT-QUOTE-TOTAL" in codes(issues)
    assert "INT-QUOTE-TOTAL" not in codes(check_request(snap(), [quote(total=D("2100.00"))]))  # 5%

    issues = check_request(snap(), [quote(valid_until=date(2026, 3, 5)), quote(issue_date=date(2026, 3, 20))])
    assert {"INT-QUOTE-EXPIRED", "INT-QUOTE-DATE"} <= codes(issues)


# ------------------------------------------------------------------ duplicates
def vec(*xs: float) -> np.ndarray:
    return np.array(xs, dtype=float)


def view(rid: str, supplier: str = "Orion Tech Ltd", total: str | None = "800.00", vectors=None,
         days: int = 0, fp: str | None = None, currency: str = "USD", category: str | None = None) -> RequestView:
    return RequestView(
        id=rid, request_no=f"PR-{rid}", supplier_name=supplier, currency=currency,
        total=D(total) if total else None, category=category,
        submitted_at=datetime(2026, 3, 1, tzinfo=UTC) + timedelta(days=days), fingerprint=fp,
        item_vectors=vectors if vectors is not None else [vec(1, 0, 0)],
    )


def test_item_set_similarity_is_symmetric_and_penalises_extra_items():
    a = [vec(1, 0, 0), vec(0, 1, 0)]
    assert item_set_similarity(a, a) == 1.0
    assert item_set_similarity(a, [vec(1, 0, 0)]) < 1.0  # b covers only half of a
    assert item_set_similarity(a, [vec(0, 0, 1)]) == 0.0
    assert item_set_similarity([], a) == 0.0
    assert item_set_similarity(a, [vec(1, 0, 0)]) == item_set_similarity([vec(1, 0, 0)], a)


def test_exact_and_similar_duplicates_and_non_duplicates():
    target = view("t", fp="abc")
    others = [
        view("exact", fp="abc", days=20),
        view("repeat", fp="abc", days=200),                                  # identical but months apart
        view("similar", supplier="ORION TECH LIMITED", vectors=[vec(0.95, 0.1, 0)], days=10),
        view("far", vectors=[vec(1, 0, 0)], days=120),                       # same items, outside window
        view("other-items", vectors=[vec(0, 1, 0)], days=5),
        view("other-supplier", supplier="Nile Cloud", vectors=[vec(1, 0, 0)], days=3),
    ]
    got = {m.other_request_no: m.kind for m in classify_duplicates(target, others)}
    assert got == {"PR-exact": "exact", "PR-repeat": "repeat_purchase", "PR-similar": "similar",
                   "PR-other-supplier": "same_items_other_supplier"}
    assert classify_duplicates(target, [target]) == []  # never matches itself
    # other supplier, identical items but 60 days apart: not flagged
    assert classify_duplicates(target, [view("x", supplier="Nile Cloud", days=60)]) == []


def test_results_are_sorted_by_score():
    target = view("t", fp="abc")
    out = classify_duplicates(target, [view("a", vectors=[vec(0.9, 0.3, 0)], days=2), view("b", fp="abc")])
    assert [m.kind for m in out] == ["exact", "similar"]


# ------------------------------------------------------------------ split purchases
def test_split_purchase_detected_when_group_crosses_threshold():
    target = view("t", total="4000.00")
    others = [view("a", total="3500.00", days=7), view("b", total="3900.00", days=20), view("far", total="9000", days=45)]
    findings = detect_splits(target, others)
    split = next(f for f in findings if f.code == "INT-SPLIT")
    assert split.threshold_usd == "5000" and split.combined_total == "11400.00"
    assert {r["request_no"] for r in split.related} == {"PR-t", "PR-a", "PR-b"}


def test_split_not_flagged_when_one_request_already_exceeds_threshold_or_other_supplier():
    assert not [f for f in detect_splits(view("t", total="6000"), [view("a", total="500", days=2)])
                if f.code == "INT-SPLIT" and f.threshold_usd == "5000"]
    assert not [f for f in detect_splits(view("t", total="900"), [view("a", supplier="Nile", total="900", days=2)])
                if f.code == "INT-SPLIT"]
    assert detect_splits(view("t", total="500"), [view("a", total="50", days=2)]) == []  # combined < 1000


def test_category_mismatch_breaks_the_group_and_unknown_category_is_disclosed():
    mismatch = detect_splits(view("t", total="900", category="it"), [view("a", total="900", category="office", days=1)])
    assert not [f for f in mismatch if f.code == "INT-SPLIT"]
    unknown = detect_splits(view("t", total="900"), [view("a", total="900", days=1)])
    assert "category not recorded" in next(f for f in unknown if f.code == "INT-SPLIT").message


def test_near_threshold_flag_and_non_usd_is_skipped():
    near = detect_splits(view("t", total="4800.00"), [])
    assert [(f.code, f.threshold_usd) for f in near] == [("INT-NEAR-THRESHOLD", "5000")]
    assert detect_splits(view("t", total="4000.00"), []) == []
    assert detect_splits(view("t", total="4800.00", currency="EUR"), []) == []
    assert detect_splits(view("t", total=None), []) == []
