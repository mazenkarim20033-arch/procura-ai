"""Analytics and audit endpoints against the live database (rolled back). Metrics are checked as DELTAS
around data this test creates, so they stay valid when the database already holds other data."""
import json
from collections import defaultdict
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditLog
from app.retrieval.embedders import HashingEmbedder
from app.retrieval.index import index_chunks
from app.services.ingest import ingest_document
from app.vendors.normalize import normalize_vendor_name
from tests.integration.helpers import wipe_all

pytestmark = pytest.mark.integration
OUT = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "out"
REV = {"x-demo-role": "reviewer", "x-demo-user": "Rami Reviewer"}
REASON = "Reviewed the quotations and the policy evidence in the assessment."


@pytest.fixture
def db():
    if not get_settings().database_url:
        pytest.skip("DATABASE_URL not configured")
    from app.db.session import get_engine

    get_engine.cache_clear()
    conn = get_engine().connect()
    trans = conn.begin()
    wipe_all(conn)
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    for pdf in sorted((OUT / "policies").glob("*.pdf")):
        ingest_document(session, filename=pdf.name, data=pdf.read_bytes(), mime="application/pdf")
    index_chunks(session, HashingEmbedder())
    yield session
    session.close()
    trans.rollback()
    conn.close()


@pytest.fixture
def client(db, monkeypatch):
    from app.api import assessments as a_api
    from app.api import requests as r_api
    from app.api import vendors as v_api
    from app.db.session import get_session
    from app.main import create_app

    emb = HashingEmbedder()
    for mod in (a_api, r_api, v_api):
        monkeypatch.setattr(mod, "get_embedder", lambda: emb)
    monkeypatch.setattr(get_settings(), "llm_provider", "mock")
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def overview(client, **params):
    r = client.get("/analytics/overview", params=params, headers=REV)
    assert r.status_code == 200, r.text
    return r.json()


GOODS = ["Quantum spectrometer", "Hydraulic press", "Ceramic kiln", "Thermal printer", "Optical bench", "Welding robot",
         "Cryogenic freezer", "Acoustic panel", "Vibration sensor"]
_counter = [0]


def mk(client, justification="Replacement of end-of-life equipment ahead of the audit season", requester="Layla Hassan"):
    """Each request gets distinct goods and a distinct supplier so the duplicate/split checks stay quiet."""
    i = _counter[0] = _counter[0] + 1
    good = GOODS[i % len(GOODS)] + f" mk{i}"
    r = client.post("/requests", json={
        "requester_name": requester, "department": "Finance", "currency": "USD", "supplier_name": f"{good.split()[0]} Trading {i} Ltd.",
        "justification": justification, "total_amount": "800.00", "submitted_on": "2026-03-10",
        "items": [{"description": good, "quantity": "2", "unit_cost": "400.00"}]})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def assess(client, rid):
    r = client.post(f"/requests/{rid}/assess", headers=REV)
    assert r.status_code == 201, r.text
    return r.json()


def decide(client, rid, action, a, reviews=None):
    r = client.post(f"/requests/{rid}/decisions", headers=REV, json={
        "action": action, "reasoning": REASON, "assessment_id": a["id"], "finding_reviews": reviews or []})
    assert r.status_code == 201, r.text


def bucket(d, *path):
    for p in path:
        d = d.get(p, {}) if isinstance(d, dict) else {}
    return d or 0


def test_analytics_match_the_data_created_by_the_workflow(db, client):
    assert client.get("/analytics/overview", headers={"x-demo-role": "requester"}).status_code == 403
    before = overview(client)
    before_clean = overview(client, exclude_mock=True)

    r1, _r2, _r3, r4, _r5 = (mk(client, requester=f"Person {i}") for i in range(5))
    r2_blank = mk(client, justification="", requester="Person 6")
    r3_blank = mk(client, justification="", requester="Person 7")
    a1, a4 = assess(client, r1), assess(client, r4)
    a2, a3 = assess(client, r2_blank), assess(client, r3_blank)
    why = [(f["rule_code"], f["category"]) for f in a1["findings"] if f["category"] != "compliant"]
    assert a1["compliance_status"] == "no_issues_found", why
    assert a2["compliance_status"] == "issues_found"
    decide(client, r1, "approve", a1)  # agrees with a clean AI result
    decide(client, r2_blank, "reject", a2)  # agrees with an AI that found issues
    fid = next(f["id"] for f in a3["findings"] if f["category"] == "confirmed_violation")
    decide(client, r3_blank, "approve", a3, [{"finding_id": fid, "verdict": "disagree", "note": "Reason supplied by phone and logged"}])
    assert a4["id"]  # r2 and r3 stay unassessed on purpose, so they remain in the review queue

    after = overview(client)
    d = lambda *path: bucket(after, *path) - bucket(before, *path)
    assert d("requests", "total") == 7
    assert (d("requests", "by_status", "approved"), d("requests", "by_status", "rejected"),
            d("requests", "by_status", "assessed"), d("requests", "by_status", "submitted")) == (2, 1, 1, 3)
    assert d("requests", "queue", "awaiting_decision") == 4 and d("requests", "queue", "awaiting_assessment") == 3
    assert d("decisions", "total") == 3 and d("decisions", "by_action", "approve") == 2 and d("decisions", "by_action", "reject") == 1
    assert d("decisions", "ai_agreement", "buckets", "agreed_with_ai") == 2
    assert d("decisions", "ai_agreement", "buckets", "approved_despite_ai_issues") == 1
    assert d("decisions", "finding_reviews", "by_verdict", "disagree") == 1
    assert d("assessments", "requests_with_assessment") == 4
    assert d("assessments", "latest_status_mix", "no_issues_found") == 2 and d("assessments", "latest_status_mix", "issues_found") == 2
    assert sum(after["assessments"]["latest_risk_distribution"].values()) - sum(before["assessments"]["latest_risk_distribution"].values()) == 4
    just = lambda o: next((r["n"] for r in o["findings"]["top_rules"] if r["rule_code"] == "R-JUSTIFICATION" and r["category"] == "confirmed_violation"), 0)
    assert just(after) - just(before) == 2

    mock_rows = [p for p in after["assessments"]["by_provider"] if p["is_mock"]]
    assert mock_rows and mock_rows[0]["provider"] == "mock" and mock_rows[0]["est_cost_usd"] is None
    assert sum(p["n"] for p in mock_rows) - sum(p["n"] for p in before["assessments"]["by_provider"] if p["is_mock"]) == 4

    t = after["decisions"]["hours_to_first_decision"]
    assert t["n"] - before["decisions"]["hours_to_first_decision"]["n"] == 3 and 0 <= t["avg_hours"] < 1  # real insertion times
    assert after["decisions"]["ai_agreement"]["agreement_rate"] is not None and "definitions" in after

    # excluding mock assessments removes every figure that depends on them
    clean = overview(client, exclude_mock=True)
    assert not [p for p in clean["assessments"]["by_provider"] if p["is_mock"]]
    assert bucket(clean, "decisions", "ai_agreement", "buckets", "agreed_with_ai") == bucket(before_clean, "decisions", "ai_agreement", "buckets", "agreed_with_ai")

    # date filters
    assert overview(client, since="2999-01-01")["requests"]["total"] == 0
    assert overview(client, until="2000-01-01")["requests"]["total"] == 0
    assert overview(client, since="2026-03-10", until="2026-03-10")["requests"]["total"] >= 7


def test_vendor_insights_match_an_independent_computation_from_the_documents(db, client):
    before = overview(client)["vendors"]
    docs = {}
    for sub in ("purchase_requests", "quotations"):
        for p in sorted((OUT / sub).glob("*.pdf")):
            docs[p.stem] = str(ingest_document(db, filename=p.name, data=p.read_bytes(), mime="application/pdf").document.id)
    expected_spreads, expected_wins, chosen_n, chosen_lowest = [], defaultdict(int), 0, 0
    for p in sorted((OUT / "purchase_requests").glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        rid = client.post(f"/requests/from-document/{docs[Path(t['file']).stem]}").json()["id"]
        quotes = []
        for q in sorted((OUT / "quotations").glob(f"quotation_{t['deal_id']}_*.json")):
            qt = json.loads(q.read_text(encoding="utf-8"))
            assert client.post(f"/requests/{rid}/documents", json={"document_id": docs[q.stem]}).status_code == 201
            quotes.append((qt["fields"]["vendor_name"], float(qt["fields"]["total"]), qt["fields"]["currency"]))
        quotes = [x for x in quotes if x[2] == t["fields"]["currency"]]
        if len(quotes) >= 2:
            lo, hi = min(quotes, key=lambda x: x[1]), max(quotes, key=lambda x: x[1])
            expected_spreads.append((hi[1] - lo[1]) / lo[1])
            expected_wins[normalize_vendor_name(lo[0])] += 1
            chosen = next((x for x in quotes if normalize_vendor_name(x[0]) == normalize_vendor_name(t["fields"]["supplier"])), None)
            if chosen:
                chosen_n += 1
                chosen_lowest += chosen[1] <= lo[1]
    after = overview(client)["vendors"]
    cmp_ = after["quotation_comparison"]
    assert cmp_["requests_compared"] - before["quotation_comparison"]["requests_compared"] == len(expected_spreads) > 0
    assert after["quotations"] - before["quotations"] == len(list((OUT / "quotations").glob("*.pdf")))
    if before["quotation_comparison"]["requests_compared"] == 0:  # absolute values only when the database started empty
        assert cmp_["avg_spread_pct"] == round(sum(expected_spreads) / len(expected_spreads) * 100, 1)
        assert cmp_["requests_with_spread_over_25pct"] == sum(s > 0.25 for s in expected_spreads)
        assert cmp_["chosen_vs_lowest"]["requests_with_chosen_quote"] == chosen_n
        assert cmp_["chosen_vs_lowest"]["chosen_was_lowest"] == chosen_lowest
        got_wins = {normalize_vendor_name(w["vendor"]): w["wins"] for w in cmp_["lowest_bidder_wins"] if w["wins"]}
        assert got_wins == dict(expected_wins)
    n_vendors = db.execute(text("select count(*) from vendors")).scalar()
    assert after["vendors"] == n_vendors and after["with_conflicts"] >= 1  # the planted Orion tax-ID conflict


def test_audit_listing_filters_pagination_and_chain_verification(db, client):
    for i in range(4):
        mk(client, requester=f"Auditee {i}")
    total = db.execute(select(func.count()).select_from(AuditLog)).scalar()
    assert client.get("/audit", headers={"x-demo-role": "requester"}).status_code == 403
    assert client.get("/audit?actor_type=bogus", headers=REV).status_code == 422

    p1 = client.get("/audit?limit=2", headers=REV).json()
    assert len(p1["entries"]) == 2 and p1["next_before_id"] == p1["entries"][-1]["id"]
    p2 = client.get(f"/audit?limit=2&before_id={p1['next_before_id']}", headers=REV).json()
    assert p2["entries"][0]["id"] < p1["entries"][-1]["id"]
    created = client.get("/audit?action=request.created&limit=200", headers=REV).json()["entries"]
    assert len(created) >= 4 and all(e["action"] == "request.created" and len(e["hash"]) == 16 for e in created)

    ok = client.get("/audit/verify", headers=REV).json()
    assert ok["ok"] is True and ok["entries_checked"] == total and ok["head_hash"] and "tamper-evident" in ok["scope"]

    # Tamper with a row (switching the immutability trigger off inside a transaction that is rolled back).
    victim = db.execute(select(AuditLog).where(AuditLog.action == "request.created").order_by(AuditLog.id)).scalars().first()
    sp = db.begin_nested()
    db.execute(text("alter table audit_log disable trigger audit_log_no_update_delete"))
    db.execute(text("update audit_log set payload_json = '{\"forged\": true}'::jsonb where id = :i"), {"i": victim.id})
    broken = client.get("/audit/verify", headers=REV).json()
    sp.rollback()
    assert broken["ok"] is False and broken["first_bad_id"] == victim.id
    assert client.get("/audit/verify", headers=REV).json()["ok"] is True  # forgery and trigger change both rolled back
