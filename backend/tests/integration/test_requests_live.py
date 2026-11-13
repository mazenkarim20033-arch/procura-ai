"""Purchase-request intake against the live database (rolled back), using the synthetic deals.
Uses the non-semantic hashing embedder: exact/near-exact description matches only."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditLog, Base
from app.retrieval.embedders import HashingEmbedder
from app.services import audit
from app.services.ingest import ingest_document

pytestmark = pytest.mark.integration
OUT = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "out"


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
    from app.api import requests as api
    from app.db.session import get_session
    from app.main import create_app

    monkeypatch.setattr(api, "get_embedder", lambda: HashingEmbedder())
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def ingest(db, path: Path):
    return ingest_document(db, filename=path.name, data=path.read_bytes(), mime="application/pdf", is_synthetic=True)


def truths(sub: str):
    return [json.loads(p.read_text(encoding="utf-8")) for p in sorted((OUT / sub).glob("*.json"))]


def test_database_schema_matches_models(db):
    rows = db.execute(text(
        "select table_name, column_name from information_schema.columns where table_schema = 'public'"
    )).all()
    actual: dict[str, set[str]] = {}
    for t, c in rows:
        actual.setdefault(t, set()).add(c)
    for name, table in Base.metadata.tables.items():
        assert actual.get(name) == {c.name for c in table.columns}, f"schema drift in {name}"
    no_rls = db.execute(text("select tablename from pg_tables where schemaname='public' and not rowsecurity")).all()
    assert no_rls == []
    assert db.execute(text("select 1 from pg_class where relname = 'request_no_seq'")).first()


def test_synthetic_deals_end_to_end(db, client):
    docs = {}  # file stem -> document id
    for sub in ("purchase_requests", "quotations"):
        for p in sorted((OUT / sub).glob("*.pdf")):
            docs[p.stem] = str(ingest(db, p).document.id)

    requests_by_deal: dict[str, dict] = {}
    for t in truths("purchase_requests"):
        stem = Path(t["file"]).stem
        r = client.post(f"/requests/from-document/{docs[stem]}", headers={"x-demo-user": "tester"})
        assert r.status_code == 201, r.text
        requests_by_deal[t["deal_id"]] = {"summary": r.json(), "truth": t}

    # attach each deal's quotations
    for t in truths("quotations"):
        stem = Path(t["file"]).stem
        rid = requests_by_deal[t["deal_id"]]["summary"]["id"]
        assert client.post(f"/requests/{rid}/documents", json={"document_id": docs[stem]}).status_code == 201

    expected_missing_dept = {t["deal_id"] for t in truths("purchase_requests") if t["fields"]["department"] is None}
    expected_total_bad = {t["deal_id"] for t in truths("purchase_requests") if "total_mismatch" in t["injected_issues"]}
    assert expected_missing_dept and expected_total_bad

    for deal, entry in requests_by_deal.items():
        rep = client.get(f"/requests/{entry['summary']['id']}/intake").json()
        codes = {i["code"] for i in rep["issues"]}
        assert ("INT-MISSING-DEPARTMENT" in codes) == (deal in expected_missing_dept), deal
        assert ("INT-TOTAL" in codes) == (deal in expected_total_bad), deal
        # No false alarms from vendor-name spelling variants, currencies, validity windows or dates.
        assert not codes & {"INT-QUOTE-SUPPLIER", "INT-QUOTE-CURRENCY", "INT-QUOTE-EXPIRED", "INT-QUOTE-DATE",
                            "INT-LINE-TOTAL", "INT-NO-QUOTATION"}, (deal, codes)
        assert rep["summary"]["quotations_attached"] >= 2
        assert rep["generated_by"].startswith("deterministic")

    detail = client.get(f"/requests/{requests_by_deal['D01']['summary']['id']}").json()
    assert detail["items"] and {d["doc_type"] for d in detail["documents"]} == {"purchase_request", "quotation"}
    assert len(client.get("/requests").json()) == 12

    entries = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert audit.verify_chain(entries) == (True, None)
    assert {e.action for e in entries} >= {"request.created", "request.document_attached"}


def req(**kw):
    base = {"requester_name": "Layla", "department": "Finance", "currency": "USD", "supplier_name": "Orion Tech Ltd.",
            "justification": "Replacement", "total_amount": "3400.00", "submitted_on": "2026-03-01",
            "items": [{"description": "Office chairs", "quantity": "10", "unit_cost": "340.00"}]}
    base.update(kw)
    return base


def test_exact_duplicate_and_split_purchase_detection(client):
    first = client.post("/requests", json=req(request_no="DUP-1")).json()
    dup = client.post("/requests", json=req(request_no="DUP-2", supplier_name="ORION TECH LIMITED",
                                            submitted_on="2026-03-05")).json()
    rep = client.get(f"/requests/{dup['id']}/intake").json()
    assert [d["kind"] for d in rep["duplicates"]] == ["exact"] and rep["duplicates"][0]["other_request_no"] == "DUP-1"
    assert rep["splits"] and rep["splits"][0]["code"] == "INT-SPLIT"  # 3,400 + 3,400 crosses 5,000

    # a request for different goods from a different supplier is neither
    other = client.post("/requests", json=req(
        request_no="OK-1", supplier_name="Nile Cloud Services", total_amount="1200.00",
        items=[{"description": "Cloud hosting monthly", "quantity": "1", "unit_cost": "1200.00"}])).json()
    rep = client.get(f"/requests/{other['id']}/intake").json()
    assert rep["duplicates"] == [] and rep["splits"] == []
    assert first["status"] == "submitted"  # intake never changes status


def test_incomplete_request_is_accepted_and_reported(client):
    r = client.post("/requests", json={"supplier_name": "Someone"})
    assert r.status_code == 201 and r.json()["request_no"].startswith("PR-")
    rep = client.get(f"/requests/{r.json()['id']}/intake").json()
    codes = {i["code"] for i in rep["issues"]}
    assert {"INT-MISSING-REQUESTER_NAME", "INT-MISSING-ITEMS", "INT-MISSING-TOTAL_AMOUNT"} <= codes
    assert rep["summary"]["errors"] >= 3


def test_non_usd_request_discloses_threshold_limitation(client):
    r = client.post("/requests", json=req(currency="EUR")).json()
    codes = {i["code"] for i in client.get(f"/requests/{r['id']}/intake").json()["issues"]}
    assert "INT-THRESHOLD-CURRENCY" in codes


def test_api_errors_and_guards(db, client):
    assert client.post("/requests", json=req(request_no="X-1")).status_code == 201
    assert client.post("/requests", json=req(request_no="X-1")).status_code == 409
    assert client.post("/requests", json={"total_amount": "-5"}).status_code == 422
    assert client.post("/requests", json={"unknown_field": 1}).status_code == 422
    missing = "00000000-0000-0000-0000-000000000000"
    assert client.get(f"/requests/{missing}").status_code == 404
    assert client.get(f"/requests/{missing}/intake").status_code == 404
    assert client.post(f"/requests/from-document/{missing}").status_code == 404

    quote = min((OUT / "quotations").glob("*.pdf"))
    qdoc = ingest(db, quote).document
    assert client.post(f"/requests/from-document/{qdoc.id}").status_code == 422  # not a purchase request

    pr = min((OUT / "purchase_requests").glob("*.pdf"))
    pdoc = ingest(db, pr).document
    first = client.post(f"/requests/from-document/{pdoc.id}")
    assert first.status_code == 201
    assert client.post(f"/requests/from-document/{pdoc.id}").status_code == 409  # already converted
    rid = first.json()["id"]
    assert client.post(f"/requests/{rid}/documents", json={"document_id": str(qdoc.id)}).status_code == 201
    assert client.post(f"/requests/{rid}/documents", json={"document_id": str(qdoc.id)}).status_code == 409
    assert client.post(f"/requests/{rid}/documents", json={"document_id": "not-a-uuid"}).status_code == 404
