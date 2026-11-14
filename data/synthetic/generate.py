"""Seeded generator for the SYNTHETIC procurement dataset (fictional company, fictional vendors).

    python data/synthetic/generate.py            # writes data/synthetic/out/**.pdf + .json truth

Every PDF carries a "SYNTHETIC DATA" footer. Each PDF has a sibling .json with the ground-truth
fields used by evals/runners/extraction.py. Documents are linked into "deals": one purchase
request, 2-3 competing quotations, and (for most deals) an invoice and/or contract that reuse the
same items and vendor, so later milestones can run realistic end-to-end scenarios.
"""
import json
import random
import re
import textwrap
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from policies import COMPANY, POLICIES
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas

SEED = 20260101
OUT = Path(__file__).parent / "out"
FOOTER = "SYNTHETIC DATA - fictional company and vendors, not a real document"
TWO = Decimal("0.01")

VENDORS = {
    "it": ["Orion Tech Supplies Ltd.", "Summit Networks Inc.", "Vertex Industrial Tools LLC"],
    "office": ["Delta Office Furniture LLC", "Cairo Print & Packaging Co.", "Lumen Lighting Solutions Ltd."],
    "services": ["BrightPath Consulting Group", "Nile Cloud Services", "Apex Facilities Management"],
}
# (description <= 30 chars, low, high)
CATALOG = {
    "it": [("Laptop 14in business", 700, 1100), ("Monitor 27in", 180, 320), ("Docking station USB-C", 90, 160),
           ("Network switch 24-port", 300, 700), ("Design software licence", 250, 600)],
    "office": [("Ergonomic office chair", 120, 300), ("Standing desk", 300, 600), ("Whiteboard 120x90", 60, 150),
               ("LED desk lamp", 25, 70), ("Printed brochures (500)", 150, 400)],
    "services": [("Consulting day rate", 400, 900), ("Cloud hosting (monthly)", 800, 2500),
                 ("Cleaning service (monthly)", 600, 1800), ("Security audit (fixed)", 3000, 9000)],
}
JUSTIFICATIONS = [
    "Replacement of end-of-life equipment used by the finance team.",
    "New hires starting next month need standard workstations.",
    "Contractor agreement ends; service must continue without interruption.",
    "Required for the planned office refurbishment on the second floor.",
    "Supports the quarterly compliance audit scheduled for next quarter.",
    "Upgrade needed to meet the new reporting deadlines.",
]
REQUESTERS = [("Layla Hassan", "Finance"), ("Omar Farouk", "IT"), ("Nadia Ibrahim", "Operations"),
              ("Karim Mansour", "HR"), ("Salma Adel", "Facilities")]
MEMOS = [
    ("INTERNAL MEMO", "Subject: Office closure on public holiday", "Please note the office will be closed on the public holiday. Plan deliveries accordingly."),
    ("MEETING MINUTES", "Subject: Weekly operations sync", "Attendees reviewed the dispatch backlog and agreed to revisit staffing next week."),
    ("INTERNAL MEMO", "Subject: Parking arrangements", "Visitor parking moves to the north lot starting Monday."),
    ("NEWSLETTER", "Subject: Company update", "Welcome to the new quarter. The cafeteria menu has been refreshed."),
]

# Fictional vendor master data (None = the vendor never states that field on its documents).
VENDOR_MASTER = {
    "Orion Tech Supplies Ltd.": {"tax_id": "TX-481-220-915", "email": "sales@oriontech.example", "phone": "+20 2 5550 0101",
                                 "address": "12 Nile Corniche, Cairo", "country": "Egypt"},
    "Summit Networks Inc.": {"tax_id": "TX-772-104-338", "email": "quotes@summitnet.example", "phone": "+1 415 555 0142",
                             "address": "500 Market Street, San Francisco", "country": "United States"},
    "Vertex Industrial Tools LLC": {"tax_id": None, "email": "info@vertextools.example", "phone": None,
                                    "address": "Industrial Zone 4, Dubai", "country": "UAE"},
    "Delta Office Furniture LLC": {"tax_id": "TX-305-889-641", "email": "orders@deltafurn.example", "phone": "+20 2 5550 0177",
                                   "address": "7 Tahrir Square, Cairo", "country": "Egypt"},
    "Cairo Print & Packaging Co.": {"tax_id": "TX-918-336-052", "email": None, "phone": "+20 2 5550 0188",
                                    "address": None, "country": "Egypt"},
    "Lumen Lighting Solutions Ltd.": {"tax_id": None, "email": "hello@lumenlight.example", "phone": "+44 20 5550 0199",
                                      "address": "21 Baker Street, London", "country": "United Kingdom"},
    "BrightPath Consulting Group": {"tax_id": "TX-264-777-410", "email": "engage@brightpath.example", "phone": None,
                                    "address": "3 Zamalek Road, Cairo", "country": "Egypt"},
    "Nile Cloud Services": {"tax_id": "TX-639-051-826", "email": "support@nilecloud.example", "phone": "+20 2 5550 0123",
                            "address": "88 Corniche Road, Alexandria", "country": "Egypt"},
    "Apex Facilities Management": {"tax_id": "TX-150-492-773", "email": "service@apexfm.example", "phone": "+20 2 5550 0155",
                                   "address": "15 Maadi Street, Cairo", "country": "Egypt"},
}
_STATE: dict = {"orion_docs": 0, "conflicts": []}


def profile_lines(vendor: str, template: str, doc_file: str) -> tuple[list[str], dict]:
    """Vendor identification lines as printed on a document, plus the truth fields. The second Orion
    quotation deliberately prints a transposed tax ID so conflict detection has something to find."""
    m = dict(VENDOR_MASTER[vendor])
    if vendor == "Orion Tech Supplies Ltd.":
        _STATE["orion_docs"] += 1
        if _STATE["orion_docs"] == 2:
            m["tax_id"] = "TX-481-220-951"
            _STATE["conflicts"].append({"vendor": vendor, "field": "tax_id", "file": doc_file, "value": m["tax_id"],
                                        "expected": VENDOR_MASTER[vendor]["tax_id"]})
    labels = ({"tax_id": "Vendor Tax ID", "address": "Vendor Address", "email": "Vendor Email",
               "phone": "Vendor Phone", "country": "Vendor Country"} if template == "A" else
              {"tax_id": "VAT No", "address": "Address", "email": "Email", "phone": "Tel", "country": "Country"})
    lines = [f"{labels[k]}: {m[k]}" for k in ("tax_id", "address", "email", "phone", "country") if m[k]]
    fields = {f"vendor_{k}": m[k] for k in ("tax_id", "address", "email", "phone", "country")}
    return lines, fields


# One flaw per document keeps the expected validation issues unambiguous.
QUOTE_FLAWS = {2: "line_total_mismatch", 5: "subtotal_mismatch", 8: "total_mismatch", 11: "missing_valid_until",
               14: "line_total_mismatch", 17: "missing_valid_until", 20: "total_mismatch", 23: "subtotal_mismatch",
               26: "missing_valid_until"}
INVOICE_FLAWS = {1: "line_total_mismatch", 4: "subtotal_mismatch", 7: "total_mismatch"}
PR_FLAWS = {3: "missing_department", 6: "total_mismatch", 9: "missing_department"}


def q2(x: Decimal) -> Decimal:
    return x.quantize(TWO, rounding=ROUND_HALF_UP)


def money(x: Decimal) -> str:
    return f"{x:,.2f}"


def plain(x: Decimal) -> str:
    return f"{x:.2f}"


def slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", s.lower()).strip("-")


def write_pdf(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(path), pagesize=A4, pageCompression=0, invariant=1)
    per_page, top, lead = 62, 800, 12
    chunks = [lines[i:i + per_page] for i in range(0, len(lines), per_page)] or [[]]
    for page in chunks:
        c.setFont("Courier-Bold", 12)
        y = top
        for i, line in enumerate(page):
            if i == 1:
                c.setFont("Courier", 10)
            c.drawString(40, y, line)
            y -= lead
        c.setFont("Courier", 8)
        c.drawString(40, 28, FOOTER)
        c.showPage()
    c.save()


def write_doc(folder: str, stem: str, lines: list[str], truth: dict) -> None:
    write_pdf(OUT / folder / f"{stem}.pdf", lines)
    truth = {"synthetic": True, "file": f"{folder}/{stem}.pdf", **truth}
    (OUT / folder / f"{stem}.json").write_text(json.dumps(truth, indent=2), encoding="utf-8")


# ----------------------------------------------------------------------------- items & totals
def make_items(rng: random.Random, category: str, currency: str, n: int) -> list[dict]:
    fx = {"USD": 1, "EUR": 1, "EGP": 45}[currency]
    picks = rng.sample(CATALOG[category], n)
    items = []
    for desc, lo, hi in picks:
        qty = rng.choice([1, 2, 5, 10, 20]) if category != "services" else rng.choice([1, 3, 6, 12])
        unit = q2(Decimal(rng.randint(lo * 100, hi * 100)) / 100 * fx)
        items.append({"description": desc, "quantity": Decimal(qty), "unit_price": unit,
                      "line_total": q2(unit * qty)})
    return items


def jitter(rng: random.Random, items: list[dict], spread: float) -> list[dict]:
    out = []
    for it in items:
        unit = q2(it["unit_price"] * Decimal(str(round(1 + rng.uniform(-spread, spread), 4))))
        out.append({**it, "unit_price": unit, "line_total": q2(unit * it["quantity"])})
    return out


def totals(items: list[dict], tax_rate: Decimal, flaw: str | None, rng: random.Random):
    """Return (printed_items, subtotal, tax, total) honouring an injected flaw."""
    printed = [dict(i) for i in items]
    if flaw == "line_total_mismatch":
        printed[0]["line_total"] = q2(printed[0]["line_total"] + Decimal(rng.randint(15, 90)))
    subtotal = sum((i["line_total"] for i in printed), Decimal(0))
    tax = q2(subtotal * tax_rate)
    if flaw == "subtotal_mismatch":
        subtotal = subtotal + Decimal(rng.randint(20, 120))
        tax = q2(subtotal * tax_rate)
    total = subtotal + tax
    if flaw == "total_mismatch":
        total = total + Decimal(rng.randint(25, 140))
    return printed, subtotal, tax, total


def items_truth(items: list[dict]) -> list[dict]:
    return [{"description": i["description"], "quantity": str(i["quantity"]), "unit_price": plain(i["unit_price"]),
             "line_total": plain(i["line_total"])} for i in items]


def row_a(i: dict) -> str:
    return f"{i['description']:<32}{int(i['quantity']):>6}{money(i['unit_price']):>14}{money(i['line_total']):>14}"


# ----------------------------------------------------------------------------- document builders
def vendor_written(rng: random.Random, name: str) -> str:
    """Vendors sometimes appear with different legal-suffix spellings (for vendor normalisation later)."""
    if rng.random() < 0.3:
        return name.replace(" Ltd.", " Limited").replace(" Inc.", " Incorporated").replace(" LLC", " L.L.C.")
    return name


def build_quotation(rng, idx, deal, vendor, items, issue, flaw):
    template = "A" if idx % 2 == 0 else "B"
    tax_rate = Decimal("0.14") if deal["currency"] == "EGP" else Decimal(0)
    printed, subtotal, tax, total = totals(items, tax_rate, flaw, rng)
    valid = None if flaw == "missing_valid_until" else issue + timedelta(days=rng.choice([14, 21, 30, 45, 60]))
    name = vendor_written(rng, vendor)
    terms = rng.choice(["Net 30", "Net 45", "Net 60", "50% advance, balance Net 30"])
    days = rng.choice([7, 14, 21, 30])
    cur, pct = deal["currency"], int(tax_rate * 100)
    if template == "A":
        qno = f"Q-2026-{idx + 1:04d}"
        lines = ["QUOTATION", f"Quotation No: {qno}", f"Date: {issue.isoformat()}"]
        if valid:
            lines.append(f"Valid Until: {valid.isoformat()}")
        plines, pfields = profile_lines(vendor, "A", f"quotations/quotation_{deal['id']}_{slug(vendor)}.pdf")
        lines += [f"Vendor: {name}", *plines, f"Currency: {cur}", f"Payment Terms: {terms}", f"Delivery: {days} days", "",
                  f"{'Description':<32}{'Qty':>6}{'Unit Price':>14}{'Line Total':>14}"]
        lines += [row_a(i) for i in printed]
        lines += ["", f"Subtotal: {money(subtotal)}", f"Tax ({pct}%): {money(tax)}", f"Total: {money(total)}"]
    else:
        qno = f"OF-{''.join(w[0] for w in vendor.split()[:2]).upper()}-{idx + 1:04d}"
        lines = ["PRICE OFFER", f"Offer Ref: {qno}", f"Issued: {issue.strftime('%d %B %Y')}"]
        if valid:
            lines.append(f"Expires: {valid.strftime('%d %B %Y')}")
        plines, pfields = profile_lines(vendor, "B", f"quotations/quotation_{deal['id']}_{slug(vendor)}.pdf")
        lines += [f"From: {name}", *plines, f"All prices in {cur}", f"Payment Terms: {terms}", f"Lead Time: {days} days", ""]
        for n, i in enumerate(printed, 1):
            lines.append(f"{n}. {int(i['quantity'])} x {i['description']} @ {cur} {money(i['unit_price'])} = {cur} {money(i['line_total'])}")
        lines += ["", f"Net Total: {money(subtotal)}", f"VAT ({pct}%): {money(tax)}", f"Total Price: {cur} {money(total)}"]
    truth = {
        "doc_type": "quotation", "template": template, "deal_id": deal["id"],
        "injected_issues": ["missing_optional"] if flaw == "missing_valid_until" else [flaw] if flaw else [],
        "fields": {
            "vendor_name": name, "quote_no": qno, "issue_date": issue.isoformat(),
            "valid_until": valid.isoformat() if valid else None, "currency": cur,
            "items": items_truth(printed), "subtotal": plain(subtotal), "tax": plain(tax), "total": plain(total),
            "payment_terms": terms, "delivery_days": days, **pfields,
        },
    }
    return f"quotation_{deal['id']}_{slug(vendor)}", lines, truth, total


def build_invoice(rng, idx, deal, vendor, items, inv_date, flaw):
    tax_rate = Decimal("0.14") if deal["currency"] == "EGP" else Decimal(0)
    printed, subtotal, tax, total = totals(items, tax_rate, flaw, rng)
    due = inv_date + timedelta(days=rng.choice([30, 45, 60]))
    ino, po, cur, pct = f"INV-2026-{idx + 1:04d}", f"PO-{deal['id']}", deal["currency"], int(tax_rate * 100)
    name = vendor_written(rng, vendor)
    plines, pfields = profile_lines(vendor, "A", f"invoices/invoice_{deal['id']}_{slug(vendor)}.pdf")
    lines = ["INVOICE", f"Invoice No: {ino}", f"Invoice Date: {inv_date.isoformat()}", f"Due Date: {due.isoformat()}",
             f"Vendor: {name}", *plines, f"PO Reference: {po}", f"Currency: {cur}", "",
             f"{'Description':<32}{'Qty':>6}{'Unit Price':>14}{'Line Total':>14}"]
    lines += [row_a(i) for i in printed]
    lines += ["", f"Subtotal: {money(subtotal)}", f"Tax ({pct}%): {money(tax)}", f"Total Due: {money(total)}"]
    truth = {
        "doc_type": "invoice", "template": "A", "deal_id": deal["id"], "injected_issues": [flaw] if flaw else [],
        "fields": {"vendor_name": name, "invoice_no": ino, "invoice_date": inv_date.isoformat(),
                   "due_date": due.isoformat(), "po_reference": po, "currency": cur, "items": items_truth(printed),
                   "subtotal": plain(subtotal), "tax": plain(tax), "total": plain(total), **pfields},
    }
    return f"invoice_{deal['id']}_{slug(vendor)}", lines, truth


def build_pr(rng, idx, deal, vendor, items, req_date, flaw):
    requester, dept = deal["requester"]
    printed, _subtotal, _, total = totals(items, Decimal(0), "total_mismatch" if flaw == "total_mismatch" else None, rng)
    rno, cur = f"PR-2026-{idx + 1:04d}", deal["currency"]
    lines = ["PURCHASE REQUEST", f"Request No: {rno}", f"Requester: {requester}"]
    if flaw != "missing_department":
        lines.append(f"Department: {dept}")
    lines += [f"Request Date: {req_date.isoformat()}", f"Supplier: {vendor}", f"Currency: {cur}",
              f"Justification: {deal['justification']}", "",
              f"{'Description':<32}{'Qty':>6}{'Unit Price':>14}{'Line Total':>14}"]
    lines += [row_a(i) for i in printed]
    lines += ["", f"Total Estimated Cost: {money(total)}"]
    truth = {
        "doc_type": "purchase_request", "template": "A", "deal_id": deal["id"],
        "injected_issues": ["missing_field"] if flaw == "missing_department" else ([flaw] if flaw else []),
        "fields": {"request_no": rno, "requester": requester,
                   "department": None if flaw == "missing_department" else dept,
                   "request_date": req_date.isoformat(), "supplier": vendor, "currency": cur,
                   "justification": deal["justification"], "items": items_truth(printed), "total": plain(total)},
    }
    return f"purchase_request_{deal['id']}", lines, truth


def build_contract(rng, idx, deal, vendor, value, start):
    cno, cur = f"CT-2026-{idx + 1:04d}", deal["currency"]
    end = start + timedelta(days=365)
    terms = rng.choice(["Net 30", "Net 45", "Net 60"])
    plines, pfields = profile_lines(vendor, "A", f"contracts/contract_{deal['id']}_{slug(vendor)}.pdf")
    lines = ["SERVICES AGREEMENT", f"Contract No: {cno}", f"Vendor: {vendor}", *plines, f"Buyer: {COMPANY}",
             f"Effective Date: {start.isoformat()}", f"End Date: {end.isoformat()}", f"Currency: {cur}",
             f"Contract Value: {money(value)}", f"Payment Terms: {terms}", "",
             "The vendor shall deliver the services described in the attached quotation.",
             "Either party may terminate this agreement with 30 days written notice.", "",
             "Signed for the buyer: ____________   Signed for the vendor: ____________"]
    truth = {"doc_type": "contract", "template": "A", "deal_id": deal["id"], "injected_issues": [],
             "fields": {"contract_no": cno, "vendor_name": vendor, "effective_date": start.isoformat(),
                        "end_date": end.isoformat(), "currency": cur, "total_value": plain(value),
                        "payment_terms": terms, **pfields}}
    return f"contract_{deal['id']}_{slug(vendor)}", lines, truth


def build_policy(p):
    lines = ["PROCUREMENT POLICY", f"Policy Code: {p['code']}", f"Title: {p['title']}", f"Version: {p['version']}",
             f"Effective Date: {p['effective_date']}", f"Category: {p['category']}", f"Company: {COMPANY}", ""]
    clauses = []
    for s_no, (s_title, texts) in enumerate(p["sections"], 1):
        lines += [f"{s_no}. {s_title}"]
        for c_no, text in enumerate(texts, 1):
            num = f"{s_no}.{c_no}"
            wrapped = textwrap.wrap(f"{num} {text}", width=88, subsequent_indent="    ")
            lines += wrapped
            clauses.append({"num": num, "section": f"{s_no} {s_title}", "text": text})
        lines.append("")
    truth = {"doc_type": "policy", "template": "policy", "injected_issues": [],
             "fields": {"code": p["code"], "title": p["title"], "version": p["version"],
                        "effective_date": p["effective_date"], "category": p["category"]},
             "clauses": clauses}
    return f"policy_{p['code'].lower()}", lines, truth


# ----------------------------------------------------------------------------- main
def main() -> None:
    rng = random.Random(SEED)
    _STATE.update({"orion_docs": 0, "conflicts": []})
    for sub in OUT.glob("*"):
        if sub.is_dir():
            for f in sub.glob("*"):
                f.unlink()
    manifest = []

    for p in POLICIES:
        stem, lines, truth = build_policy(p)
        write_doc("policies", stem, lines, truth)

    quote_i = invoice_i = contract_i = 0
    categories = ["it", "it", "office", "services", "it", "office", "services", "it", "office", "services", "it", "services"]
    currencies = ["USD"] * 8 + ["EUR", "EUR", "EGP", "EGP"]
    rng.shuffle(currencies)
    for d in range(12):
        cat, cur = categories[d], currencies[d]
        deal = {"id": f"D{d + 1:02d}", "category": cat, "currency": cur, "requester": rng.choice(REQUESTERS),
                "justification": rng.choice(JUSTIFICATIONS)}
        pr_date = date(2026, 1, 5) + timedelta(days=d * 9)
        base_items = make_items(rng, cat, cur, rng.choice([1, 2, 3]))
        vendors = rng.sample(VENDORS[cat], rng.choice([2, 3]))
        chosen = vendors[0]

        quote_totals = {}
        for v in vendors:
            issue = pr_date - timedelta(days=rng.randint(3, 10))
            stem, lines, truth, total = build_quotation(
                rng, quote_i, deal, v, jitter(rng, base_items, 0.12), issue, QUOTE_FLAWS.get(quote_i))
            write_doc("quotations", stem, lines, truth)
            quote_totals[v] = total
            quote_i += 1

        stem, lines, truth = build_pr(rng, d, deal, chosen, base_items, pr_date, PR_FLAWS.get(d))
        write_doc("purchase_requests", stem, lines, truth)

        if d % 3 != 2:  # most deals reach an invoice
            stem, lines, truth = build_invoice(
                rng, invoice_i, deal, chosen, jitter(rng, base_items, 0.05),
                pr_date + timedelta(days=rng.randint(14, 30)), INVOICE_FLAWS.get(invoice_i))
            write_doc("invoices", stem, lines, truth)
            invoice_i += 1
        if cat == "services":
            stem, lines, truth = build_contract(rng, contract_i, deal, chosen, quote_totals[chosen],
                                                pr_date + timedelta(days=10))
            write_doc("contracts", stem, lines, truth)
            contract_i += 1

    # contracts to reach a useful sample size (stand-alone, not tied to a deal)
    for k in range(contract_i, 6):
        deal = {"id": f"X{k + 1:02d}", "currency": "USD"}
        vendor = rng.choice(VENDORS["services"])
        stem, lines, truth = build_contract(rng, k, deal, vendor, Decimal(rng.randint(8, 60) * 1000),
                                            date(2026, 2, 1) + timedelta(days=k * 20))
        write_doc("contracts", stem, lines, truth)

    for n, (title, subj, body) in enumerate(MEMOS, 1):
        write_doc("other", f"memo_{n:02d}", [title, subj, "", *textwrap.wrap(body, 88)],
                  {"doc_type": "other", "template": "memo", "injected_issues": [], "fields": {}})

    for f in sorted(OUT.glob("*/*.json")):
        t = json.loads(f.read_text(encoding="utf-8"))
        manifest.append({"file": t["file"], "doc_type": t["doc_type"], "deal_id": t.get("deal_id")})
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    (OUT / "vendor_truth.json").write_text(json.dumps({
        "synthetic": True, "vendors": VENDOR_MASTER, "conflicts": _STATE["conflicts"],
        "note": "Master data is what each vendor prints on its documents; conflicts are deliberate deviations."},
        indent=2), encoding="utf-8")
    counts = {}
    for m in manifest:
        counts[m["doc_type"]] = counts.get(m["doc_type"], 0) + 1
    print(f"wrote {len(manifest)} documents to {OUT}: {counts}")


if __name__ == "__main__":
    main()
