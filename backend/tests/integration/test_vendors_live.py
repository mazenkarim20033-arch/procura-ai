"""Vendor records, quotation storage and comparison against the live database (rolled back)."""
import json
from pathlib import Path
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditLog, PurchaseRequest, Quotation, Vendor, VendorAlias
from app.retrieval.embedders import HashingEmbedder
from app.services import audit
from app.services import vendors as svc
from app.services.ingest import ingest_document

pytestmark = pytest.mark.integration
OUT = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "out"
TRUTH = json.loads((OUT / "vendor_truth.json").read_text(encoding="utf-8"))


@pytest.fixture
def db():
    if not get_settings().database_url:
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import get_engine

    get_engine.cache_clear()
    conn = get_engine().connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    from app.api import requests as r_api
    from app.api import vendors as v_api
    from app.db.session import get_session
    from app.main import create_app

    emb = HashingEmbedder()
    monkeypatch.setattr(v_api, "get_embedder", lambda: emb)
    monkeypatch.setattr(r_api, "get_embedder", lambda: emb)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def ingest_all(db, *subs):
    docs = {}
    for sub in subs:
        for p in sorted((OUT / sub).glob("*.pdf")):
            docs[p.stem] = ingest_document(db, filename=p.name, data=p.read_bytes(), mime="application/pdf").document.id
    return docs


def test_vendor_records_from_synthetic_documents_match_the_master_data(db, client):
    ingest_all(db, "quotations", "invoices", "contracts")
    listing = client.get("/vendors").json()
    names = {v["name"] for v in listing}
    # legal-suffix spellings (Ltd/Limited, Inc/Incorporated, LLC/L.L.C.) must not create duplicate vendors
    assert len(names) == len(listing) and names <= set(TRUTH["vendors"]), names - set(TRUTH["vendors"])
    assert all(v["basis"].startswith("Based only on the uploaded documents") for v in listing)

    for v in listing:
        detail = client.get(f"/vendors/{v['id']}").json()
        master = TRUTH["vendors"][v["name"]]
        codes = {g["code"] for g in detail["gaps"]}
        assert detail["country"] == master["country"]
        assert (detail["tax_id"] is None) == (master["tax_id"] is None) or v["name"] == "Orion Tech Supplies Ltd."
        assert ("VND-MISSING-TAX_ID" in codes) == (master["tax_id"] is None), v["name"]
        assert ("VND-MISSING-EMAIL" in codes) == (master["email"] is None), v["name"]
        assert ("VND-MISSING-ADDRESS" in codes) == (master["address"] is None), v["name"]
        assert ("VND-MISSING-PHONE" in codes) == (master["phone"] is None), v["name"]

    # the deliberate tax-ID conflict on the second Orion quotation is surfaced, and the first value is kept
    orion = next(v for v in listing if v["name"] == "Orion Tech Supplies Ltd.")
    d = client.get(f"/vendors/{orion['id']}").json()
    assert d["tax_id"] == TRUTH["vendors"]["Orion Tech Supplies Ltd."]["tax_id"]
    assert "VND-CONFLICT" in {g["code"] for g in d["gaps"]}
    assert d["quotations"]


def test_quote_comparison_matches_injected_flaws_and_attaches_prices(db, client):
    docs = ingest_all(db, "purchase_requests", "quotations")
    flawed = {Path(t["file"]).stem for t in (json.loads(p.read_text(encoding="utf-8")) for p in (OUT / "quotations").glob("*.json"))
              if any(c.endswith("_mismatch") for c in t["injected_issues"])}
    assert flawed
    seen_flagged = set()
    for p in sorted((OUT / "purchase_requests").glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        rid = client.post(f"/requests/from-document/{docs[Path(t['file']).stem]}").json()["id"]
        req = db.execute(select(PurchaseRequest).where(PurchaseRequest.id == UUID(rid))).scalar_one()
        assert req.supplier_id is not None  # the requested supplier already exists as a vendor from its quotation
        for q in sorted((OUT / "quotations").glob(f"quotation_{t['deal_id']}_*.json")):
            qs = Path(q.name).stem
            assert client.post(f"/requests/{rid}/documents", json={"document_id": str(docs[qs])}).status_code == 201
        res = client.get(f"/requests/{rid}/quote-comparison").json()
        assert res["basis"].startswith("Based only on the uploaded documents")
        assert len(res["quotes"]) >= 2 and res["item_rows"]
        flagged = {f["message"].split(" has arithmetic")[0] for f in res["flags"] if f["code"] == "CMP-ARITHMETIC"}
        seen_flagged |= {Path(x).stem for x in flagged}
        assert not {f["code"] for f in res["flags"]} & {"CMP-PRICE-OUTLIER", "CMP-SUSPICIOUSLY-LOW"}  # jitter is +-12%
    assert seen_flagged == flawed  # every injected arithmetic flaw found, nothing else flagged
    assert db.execute(select(Quotation).where(Quotation.request_id.is_not(None))).first()


def test_merge_vendors_is_admin_only_and_moves_everything(db, client):
    a, _ = svc.record_vendor(db, name="Zeta Supplies Ltd", doc_id=None, tax_id="TX-1")
    b, _ = svc.record_vendor(db, name="Zeta Supplies Trading", doc_id=None, tax_id="TX-2", email="z@z.example")
    db.add(Quotation(vendor_id=b.id, currency="USD", total=100))
    db.flush()
    r = client.post(f"/vendors/{b.id}/merge", json={"into_vendor_id": str(a.id)}, headers={"x-demo-role": "reviewer"})
    assert r.status_code == 403
    r = client.post(f"/vendors/{b.id}/merge", json={"into_vendor_id": str(a.id)}, headers={"x-demo-role": "admin", "x-demo-user": "boss"})
    assert r.status_code == 200
    d = r.json()
    assert d["name"] == "Zeta Supplies Ltd" and "Zeta Supplies Trading" in d["aliases"] and len(d["quotations"]) == 1
    assert d["contact"]["email"] == "z@z.example" and "VND-CONFLICT" in {g["code"] for g in d["gaps"]}  # TX-1 vs TX-2
    assert db.get(Vendor, b.id) is None
    assert client.post(f"/vendors/{a.id}/merge", json={"into_vendor_id": str(a.id)}, headers={"x-demo-role": "admin"}).status_code == 409
    assert client.get(f"/vendors/{b.id}").status_code == 404
    entries = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert audit.verify_chain(entries) == (True, None)
    assert any(e.action == "vendor.merged" for e in entries)


def test_name_variants_and_fuzzy_matches_create_aliases_not_duplicates(db):
    a, _ = svc.record_vendor(db, name="Nile Cloud Services", doc_id=None, tax_id="TX-9")
    b, d2 = svc.record_vendor(db, name="NILE CLOUD SERVICES LTD", doc_id=None)
    assert b.id == a.id and d2.reason == "name"
    c, d3 = svc.record_vendor(db, name="Nile Cloud Servces", doc_id=None)  # typo -> fuzzy, flagged for review
    assert c.id == a.id and d3.reason == "fuzzy" and d3.needs_review
    other, d4 = svc.record_vendor(db, name="Nile Cloud Solutions", doc_id=None, tax_id="TX-77")
    assert other.id != a.id and d4.action == "new"
    aliases = {x.alias for x in db.execute(select(VendorAlias).where(VendorAlias.vendor_id == a.id)).scalars()}
    assert aliases == {"Nile Cloud Servces"}  # a case/suffix variant of the same normalised name needs no alias
    assert svc.find_vendor_by_name(db, "nile cloud services").id == a.id
    assert svc.find_vendor_by_name(db, "Nile Cloud Servces").id == a.id  # known alias
    assert svc.find_vendor_by_name(db, "Unknown Vendor GmbH") is None
