from datetime import date
from decimal import Decimal

from app.vendors.compare import HistoryPoint, ItemQ, QuoteQ, compare_quotes
from app.vendors.resolve import Candidate, Profile, normalize_tax_id, resolve_vendor

D = Decimal


# ------------------------------------------------------------------ resolution
def cands():
    return [Candidate("v1", "Orion Tech Supplies Ltd.", "TX-481-220-915", ["Orion Tech"]),
            Candidate("v2", "Nile Cloud Services", None, [])]


def test_tax_id_wins_even_when_names_differ():
    d = resolve_vendor(Profile("Totally Different Trading Name", "tx 481 220 915"), cands())
    assert (d.action, d.vendor_id, d.reason, d.needs_review) == ("match", "v1", "tax_id", False)
    assert normalize_tax_id(" tx-481/220 915 ") == "TX481220915" and normalize_tax_id("") is None


def test_name_alias_and_suffix_variants_match_without_review():
    for name, reason in [("ORION TECH SUPPLIES LIMITED", "name"), ("Orion Tech", "alias"), ("nile cloud services ltd", "name")]:
        d = resolve_vendor(Profile(name), cands())
        assert d.action == "match" and d.reason == reason and not d.needs_review, name


def test_same_name_with_a_different_tax_id_is_a_conflict_to_review_not_a_new_vendor():
    d = resolve_vendor(Profile("Orion Tech Supplies Ltd.", "TX-481-220-951"), cands())
    assert d.action == "match" and d.vendor_id == "v1" and d.needs_review
    assert d.conflicts == [{"field": "tax_id", "existing": "TX-481-220-915", "new": "TX-481-220-951"}]


def test_fuzzy_matches_are_flagged_for_review_and_blocked_by_different_tax_ids():
    d = resolve_vendor(Profile("Nile Cloud Servces"), cands())  # typo
    assert d.action == "match" and d.reason == "fuzzy" and d.needs_review and d.score >= 0.92
    near = [Candidate("v9", "Nile Cloud Services", "TX-1", [])]
    assert resolve_vendor(Profile("Nile Cloud Servces", "TX-2"), near).action == "new"
    assert resolve_vendor(Profile("Nile Cloud Solutions"), cands()).action == "new"  # a different company
    assert resolve_vendor(Profile("Completely Unknown Co"), cands()).action == "new"
    assert resolve_vendor(Profile(""), cands()).action == "new"


# ------------------------------------------------------------------ comparison
def item(desc, qty, price, vec=None):
    return ItemQ(desc, D(qty), D(price), D(qty) * D(price), vec)


def quote(key, label, items, total, currency="USD", tax=None, terms="Net 30", valid=date(2026, 5, 1), delivery=14, codes=None):
    return QuoteQ(key, key.title(), label, currency, D(total), D(total) - (D(tax) if tax else 0), D(tax) if tax else None,
                  delivery, terms, date(2026, 3, 1), valid, items, codes or [])


def three():
    return [
        quote("orion", "q-orion", [item("Laptop 14in business", 10, 1000), item("Docking station USB-C", 10, 100)], 11000),
        quote("summit", "q-summit", [item("14-inch business laptop", 10, 1050), item("USB-C dock", 10, 95)], 11450),
        quote("vertex", "q-vertex", [item("Business laptop 14 inch", 10, 1020), item("Docking station", 10, 105)], 11250),
    ]


def codes(res):
    return [f["code"] for f in res["flags"]]


def test_ranking_item_alignment_and_clean_comparison():
    res = compare_quotes(three(), date(2026, 3, 10), request_currency="USD")
    assert [r["label"] for r in res["ranking"]] == ["q-orion", "q-vertex", "q-summit"]
    assert len(res["item_rows"]) == 2  # paraphrased descriptions are aligned into two rows (token overlap fallback)
    assert res["basis"].startswith("Based only on the uploaded documents")
    assert "CMP-PRICE-OUTLIER" not in codes(res) and "CMP-SUSPICIOUSLY-LOW" not in codes(res)
    assert any("Spread" in n for n in res["notes"])


def test_price_outlier_and_suspiciously_low_price():
    qs = three()
    qs[2] = quote("vertex", "q-vertex", [item("Business laptop 14 inch", 10, 1900), item("Docking station", 10, 105)], 20050)
    res = compare_quotes(qs, date(2026, 3, 10), request_currency="USD")
    assert "CMP-PRICE-OUTLIER" in codes(res)
    qs = three()
    qs[1] = quote("summit", "q-summit", [item("14-inch business laptop", 10, 400), item("USB-C dock", 10, 95)], 4950)
    res = compare_quotes(qs, date(2026, 3, 10), request_currency="USD")
    assert "CMP-SUSPICIOUSLY-LOW" in codes(res)


def test_two_quotes_report_gap_not_outlier_and_one_quote_cannot_be_compared():
    res = compare_quotes(three()[:2], date(2026, 3, 10))
    assert "CMP-PRICE-OUTLIER" not in codes(res)
    res = compare_quotes([quote("orion", "q", [item("Laptop", 1, 100), item("Dock", 1, 10)], 110),
                          quote("summit", "q2", [item("Laptop", 1, 200), item("Dock", 1, 10)], 210)], None)
    assert "CMP-PRICE-GAP" in codes(res)
    one = compare_quotes(three()[:1], None)
    assert any("Fewer than two" in n for n in one["notes"]) and one["item_rows"] == []
    assert compare_quotes([], None)["notes"] == ["No quotations attached to compare."]


def test_currencies_are_never_converted_and_tax_changes_the_ranking_basis():
    qs = three()
    qs[2] = quote("vertex", "q-vertex", [item("Laptop 14in business", 10, 900)], 9000, currency="EUR")
    res = compare_quotes(qs, date(2026, 3, 10), request_currency="USD")
    assert "CMP-CURRENCY" in codes(res) and "q-vertex" not in [r["label"] for r in res["ranking"]]
    qs = three()
    qs[0] = quote("orion", "q-orion", [item("Laptop 14in business", 10, 1000)], 11400, tax=1400)  # 14% VAT included
    res = compare_quotes(qs, date(2026, 3, 10), request_currency="USD")
    assert any("subtotals" in n for n in res["notes"]) and "subtotal" in res["ranking"][0]


def test_quote_level_flags_and_terms():
    qs = three()
    qs[0] = quote("orion", "q-orion", qs[0].items, 11000, valid=date(2026, 3, 1), codes=["total_mismatch"], terms="50% advance, balance Net 30")
    qs[1] = quote("summit", "q-summit", qs[1].items, 11450, valid=None)
    res = compare_quotes(qs, date(2026, 3, 10), request_currency="USD")
    assert {"CMP-ARITHMETIC", "CMP-EXPIRED", "CMP-NO-VALIDITY"} <= set(codes(res))
    orion = next(q for q in res["quotes"] if q["label"] == "q-orion")
    assert orion["net_days"] == 30 and orion["advance_pct"] == "50" and orion["validity_days_from_request"] == -9


def test_missing_item_and_quantity_differences():
    qs = three()
    qs[2] = quote("vertex", "q-vertex", [item("Business laptop 14 inch", 12, 1020)], 12240)
    res = compare_quotes(qs, date(2026, 3, 10), request_currency="USD")
    assert {"CMP-MISSING-ITEM", "CMP-QTY-DIFFERS"} <= set(codes(res))


def test_vendor_price_history():
    hist = [HistoryPoint("orion", "Laptop 14in business", D("700"), "USD", date(2025, 11, 1)),
            HistoryPoint("orion", "Laptop 14in business", D("720"), "USD", date(2025, 12, 1)),
            HistoryPoint("summit", "Laptop 14in business", D("1000"), "USD", date(2025, 12, 1))]
    res = compare_quotes(three(), date(2026, 3, 10), request_currency="USD", history=hist)
    h = [f for f in res["flags"] if f["code"] == "CMP-HISTORY"]
    assert len(h) == 1 and h[0]["vendor"] == "Orion" and "+" in h[0]["message"]  # only Orion's own history counts
    stable = [HistoryPoint("orion", "Laptop 14in business", D("990"), "USD", date(2025, 12, 1))]
    assert "CMP-HISTORY" not in codes(compare_quotes(three(), date(2026, 3, 10), history=stable))
