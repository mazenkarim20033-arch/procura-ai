"""Seed the database with the SYNTHETIC demo dataset so the UI has something real to explore.

    cd backend && .venv/Scripts/python scripts/seed_demo.py [--provider mock|configured] [--yes]

Everything goes through the normal services (ingestion, request intake, assessment, decisions), so the
result is indistinguishable from data entered by hand, except that documents and requests are flagged
`is_synthetic` and assessments from the default `mock` provider are flagged `is_mock` (the UI shows both).

What it creates: the 6 policies (embedded), 12 purchase requests from the synthetic request documents with
their quotations, invoices and contracts attached, an approved-supplier list (two vendors are left off on
purpose), an assessment per request, and a handful of human decisions so the queue, history and analytics
are populated. Some requests are left undecided and one has an open information request.

It refuses to run twice. NOTE: the audit log is append-only by design (database triggers), so seeded entries
cannot be removed afterwards; use a fresh database branch if you need a clean slate.
"""
import argparse
import hashlib
import json
import sys
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ai.providers.factory import build_provider
from app.ai.providers.mock import MockProvider
from app.db import enums as E
from app.db.models import Document, DocumentPage, Extraction, PurchaseRequest
from app.db.session import get_engine
from app.retrieval.embedders import get_embedder
from app.retrieval.index import index_chunks
from app.schemas.decisions import DecisionIn
from app.schemas.identity import CurrentUser
from app.schemas.requests import ItemIn, RequestCreate
from app.services import assessment as assess_svc
from app.services import decisions as dec_svc
from app.services import requests as req_svc
from app.services import vendors as vendor_svc
from app.services.ingest import ingest_document

OUT = ROOT / "data" / "synthetic" / "out"
STORAGE = ROOT / "backend" / "storage"
APPROVED = ["Orion Tech Supplies Ltd.", "Summit Networks Inc.", "Delta Office Furniture LLC", "Cairo Print & Packaging Co.",
            "BrightPath Consulting Group", "Nile Cloud Services", "Apex Facilities Management"]  # Vertex and Lumen are left off
USERS = {
    "officer": CurrentUser("Rami Haddad", E.Role.reviewer, "procurement officer"),
    "director": CurrentUser("Dina Samir", E.Role.reviewer, "finance director"),
    "cfo": CurrentUser("Omar Nassar", E.Role.admin, "chief financial officer"),
}
REASONS = {
    "approve": "Quotations compared, supplier and totals match the request, no policy issues in the assessment.",
    "reject": "The assessment found problems with the supporting documents that the supplier must correct first.",
    "request_info": "Please attach quotations from at least two other suppliers and confirm the quote validity dates.",
}


def user_for(req: PurchaseRequest):
    if req.currency != "USD" or req.total_amount is None:
        return USERS["cfo"]
    return USERS["director"] if req.total_amount > 1000 else USERS["officer"]


GOODS = ["Quantum spectrometer", "Hydraulic press", "Ceramic kiln", "Thermal label printer", "Optical test bench", "Welding robot arm",
         "Cryogenic freezer", "Acoustic wall panels", "Vibration sensor kit", "Ergonomic workstation chairs", "Network rack cabinet",
         "Industrial label printer", "Fume extraction unit", "Calibration weights set", "Conference room displays", "Backup power units",
         "Laboratory glassware"]
# Scenarios chosen for a varied tour; v02/m04 depend on a different approved-supplier list so they are left out.
PICK = [("c01", "approve"), ("c03", None), ("c04", "approve"), ("c07", None), ("v01", "reject"), ("v04", "reject"), ("v05", None),
        ("v03", None), ("m01", "request_info"), ("m03", None), ("m07", None), ("a01", None), ("a03", None), ("a04", None),
        ("a05", None), ("x01", None), ("x04", None)]


def _render(kind: str, raw: dict) -> str:
    lines = ["SYNTHETIC DEMO DOCUMENT generated from structured data (there is no PDF behind it)", kind.upper()]
    for k, v in raw.items():
        if k != "items":
            lines.append(f"{k.replace('_', ' ').title()}: {v}")
    for it in raw.get("items", []):
        lines.append(f"{it['description']}  {it['quantity']}  {it['unit_price']}  {it['line_total']}")
    return "\n".join(lines)


def _doc(s: Session, filename: str, doc_type: E.DocType, raw: dict, issues: list[dict]) -> Document:
    text = _render(doc_type.value, raw)
    doc = Document(filename=filename, sha256=hashlib.sha256((filename + text).encode()).hexdigest(), mime="text/plain",
                   doc_type=doc_type, doc_type_confidence=Decimal("1.000"), language="en", is_synthetic=True,
                   status=E.DocStatus.extracted, page_count=1)
    s.add(doc)
    s.flush()
    s.add(DocumentPage(document_id=doc.id, page_no=1, text=text))
    s.add(Extraction(document_id=doc.id, schema_name="QuotationData" if doc_type == E.DocType.quotation else "ContractData",
                     schema_version="1", data_json=raw, field_provenance_json={}, validation_errors_json=issues, method="mock"))
    s.flush()
    return doc


def _issues(codes: list[str]) -> list[dict]:
    out = []
    for c in codes:
        if ":" in c:
            kind, field = c.split(":", 1)
            out.append({"field": field, "code": kind, "message": "Missing or invalid in the source data"})
        else:
            out.append({"field": "total", "code": c, "message": "Totals do not add up in the source data"})
    return out


def seed_scenarios(s: Session, embedder, provider) -> None:
    scenarios = {x["id"]: x for x in json.loads((ROOT / "evals" / "datasets" / "compliance_scenarios.json").read_text(encoding="utf-8"))}
    master = json.loads((OUT / "vendor_truth.json").read_text(encoding="utf-8"))["vendors"]
    today = date.today()
    n = len(PICK)
    results = []
    for i, (sid, action) in enumerate(PICK):
        sc = scenarios[sid]
        r = sc["request"]
        submitted = today - timedelta(days=(n - i) * 3 + 1)
        delta = (submitted - date.fromisoformat(r["submitted_on"])).days

        def shift(d, delta=delta):
            return (date.fromisoformat(d) + timedelta(days=delta)).isoformat() if d else None

        names = {"Orion Tech Supplies Ltd.": APPROVED[i % 7], "Summit Networks Inc.": APPROVED[(i + 1) % 7],
                 "Vertex Industrial Tools LLC": APPROVED[(i + 2) % 7], "Nile Cloud Services": APPROVED[(i + 3) % 7]}

        def rename(v, names=names):
            return names.get(v, v) if v else v

        total = Decimal(r["total_amount"]) if r["total_amount"] else None
        good = GOODS[i % len(GOODS)]
        description = r["items"][0]["description"] if "</system>" in r["items"][0]["description"] else good
        qty = Decimal(10)
        payload = RequestCreate(
            request_no=f"DEMO-{sid.upper()}", requester_name=r["requester_name"], department=r["department"], currency=r["currency"],
            supplier_name=rename(r["supplier_name"]), justification=r["justification"] or None, total_amount=total, submitted_on=submitted,
            items=[ItemIn(description=description, quantity=qty, unit_cost=(total / qty).quantize(Decimal("0.01")) if total else None)])
        req = req_svc.create_request(s, payload, actor="seed", embedder=embedder, is_synthetic=True)
        for q_i, q in enumerate(sc["quotes"]):
            vendor = rename(q["vendor"])
            prof = master.get(vendor, {})
            raw = {"vendor_name": vendor, "quote_no": f"Q-DEMO-{sid.upper()}-{q_i + 1}", "issue_date": shift(q["issue_date"]),
                   "valid_until": shift(q["valid_until"]), "currency": q["currency"], "total": q["total"], "subtotal": q["total"], "tax": "0.00",
                   "payment_terms": q["payment_terms"], "delivery_days": 14,
                   "vendor_tax_id": prof.get("tax_id"), "vendor_email": prof.get("email"), "vendor_phone": prof.get("phone"),
                   "vendor_address": prof.get("address"), "vendor_country": prof.get("country"),
                   "items": [{"description": good, "quantity": "10", "unit_price": f"{Decimal(q['total']) / 10:.2f}", "line_total": q["total"]}]}
            raw = {k: v for k, v in raw.items() if v is not None}
            issues = _issues(q["issue_codes"])
            doc = _doc(s, f"{sid.upper()} quotation from {vendor}.txt", E.DocType.quotation, raw, issues)
            vendor_svc.record_from_document(s, doc, raw, issues)
            req_svc.attach_document(s, req.id, doc.id, None, actor="seed")
        for c_i, c in enumerate(sc["contracts"]):
            vendor = rename(c["vendor"])
            prof = master.get(vendor, {})
            raw = {"contract_no": f"CT-DEMO-{sid.upper()}-{c_i + 1}", "vendor_name": vendor, "effective_date": shift(r["submitted_on"]),
                   "currency": c["currency"], "total_value": c["total_value"], "payment_terms": c["payment_terms"],
                   "vendor_tax_id": prof.get("tax_id"), "vendor_country": prof.get("country")}
            raw = {k: v for k, v in raw.items() if v is not None}
            doc = _doc(s, f"{sid.upper()} contract with {vendor}.txt", E.DocType.contract, raw, [])
            vendor_svc.record_from_document(s, doc, raw, [])
            req_svc.attach_document(s, req.id, doc.id, None, actor="seed")
        s.commit()
        a = assess_svc.assess_request(s, req.id, provider=provider, embedder=embedder, actor="seed")
        s.commit()
        print(f"{req.request_no}: {a.compliance_status.value} / {a.overall_risk.value}")
        results.append((req, a, action))

    for req, a, action in results:
        if not action:
            continue
        if req.currency != "USD" or req.total_amount is None:
            user = USERS["cfo"]
        else:
            user = USERS["director"] if req.total_amount > 1000 else USERS["officer"]
        confirmed = [f for f in dec_svc._assessment_view(s, a).findings if f.category == "confirmed_violation"]
        if action == "approve" and (confirmed or a.compliance_status != E.ComplianceStatus.no_issues_found):
            print(f"left {req.request_no} undecided: the assessment would not support an approval")
            continue
        body = DecisionIn(action=action, reasoning=REASONS[action], assessment_id=a.id if action != "request_info" else None)
        try:
            dec_svc.record_decision(s, req.id, body, user)
            s.commit()
            print(f"decision {action}: {req.request_no}")
        except Exception as exc:  # noqa: BLE001 - a demo seed reports and continues
            s.rollback()
            print(f"skipped {action} for {req.request_no}: {exc}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", choices=["mock", "configured"], default="mock")
    ap.add_argument("--scenarios", action="store_true", help="add the designed scenario requests (run the base seed first)")
    ap.add_argument("--yes", action="store_true", help="skip the confirmation prompt")
    args = ap.parse_args()

    engine = get_engine()
    with Session(engine, expire_on_commit=False) as s:
        if args.scenarios:
            if s.execute(select(func.count()).select_from(PurchaseRequest).where(PurchaseRequest.request_no.like('DEMO-%'))).scalar():
                sys.exit('Scenario requests already exist; refusing to add them twice.')
            if not args.yes and input("Add the scenario requests to the database? Type 'seed': ").strip() != 'seed':
                sys.exit('Cancelled.')
            seed_scenarios(s, get_embedder(), MockProvider() if args.provider == 'mock' else build_provider())
            print('scenarios done.')
            return
        if s.execute(select(func.count()).select_from(PurchaseRequest).where(PurchaseRequest.is_synthetic)).scalar():
            sys.exit("Synthetic requests already exist; refusing to seed twice.")
        print("This writes the synthetic dataset (documents, requests, assessments, decisions, audit entries) into the "
              "configured database.")
        if not args.yes and input("Type 'seed' to continue: ").strip() != "seed":
            sys.exit("Cancelled.")

        embedder = get_embedder()
        docs: dict[str, str] = {}
        for folder in ("policies", "purchase_requests", "quotations", "invoices", "contracts", "other"):
            for pdf in sorted((OUT / folder).glob("*.pdf")):
                r = ingest_document(s, filename=pdf.name, data=pdf.read_bytes(), mime="application/pdf",
                                    is_synthetic=True, storage_dir=STORAGE)
                docs[f"{folder}/{pdf.stem}"] = str(r.document.id)
            s.commit()
            print(f"ingested {folder}")
        index_chunks(s, embedder)
        s.commit()
        print("policy clauses embedded")
        assess_svc.set_approved_suppliers(s, APPROVED, actor="seed")
        s.commit()

        provider = MockProvider() if args.provider == "mock" else build_provider()
        deals: dict[str, dict] = {}
        for t in sorted((OUT / "purchase_requests").glob("*.json")):
            meta = json.loads(t.read_text(encoding="utf-8"))
            deals[meta["deal_id"]] = {"pr": f"purchase_requests/{t.stem}"}
        requests: dict[str, str] = {}
        for deal, info in deals.items():
            req = req_svc.create_from_document(s, uuid.UUID(docs[info["pr"]]), actor="seed", embedder=embedder)
            requests[deal] = str(req.id)
            for folder in ("quotations", "invoices", "contracts"):
                for j in sorted((OUT / folder).glob(f"*_{deal}_*.json")):
                    req_svc.attach_document(s, req.id, uuid.UUID(docs[f"{folder}/{j.stem}"]), None, actor="seed")
            s.commit()
        print(f"created {len(requests)} requests")

        assessed = {}
        for deal, rid in requests.items():
            a = assess_svc.assess_request(s, uuid.UUID(rid), provider=provider, embedder=embedder, actor="seed")
            s.commit()
            assessed[deal] = a
            print(f"assessed {deal}: {a.compliance_status.value} / {a.overall_risk.value}")

        # A few human decisions, chosen from the assessment results so the story is coherent.
        counts = {"approve": 0, "reject": 0, "request_info": 0}
        for _deal, a in sorted(assessed.items()):
            req = s.get(PurchaseRequest, a.request_id)
            confirmed = [f for f in dec_svc._assessment_view(s, a).findings if f.category == "confirmed_violation"]
            action = None
            if a.compliance_status == E.ComplianceStatus.no_issues_found and counts["approve"] < 3:
                action = "approve"
            elif confirmed and counts["reject"] < 2:
                action = "reject"
            elif a.compliance_status == E.ComplianceStatus.needs_information and counts["request_info"] < 1:
                action = "request_info"
            if not action:
                continue
            user = USERS["cfo"] if action == "approve" and user_for(req) is USERS["cfo"] else user_for(req)
            body = DecisionIn(action=action, reasoning=REASONS[action], assessment_id=a.id if action != "request_info" else None)
            try:
                dec_svc.record_decision(s, a.request_id, body, user)
                s.commit()
                counts[action] += 1
                print(f"decision {action}: {req.request_no}")
            except Exception as exc:  # noqa: BLE001 - a rule refused it (e.g. approval level); leave the request pending
                s.rollback()
                print(f"skipped {action} for {req.request_no}: {exc}")
        print("done.", counts)


if __name__ == "__main__":
    main()
