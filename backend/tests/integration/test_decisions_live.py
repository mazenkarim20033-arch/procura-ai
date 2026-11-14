"""Human approval workflow against the live database (rolled back): mock LLM, hashing embedder."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditLog, Decision, FindingReview, InfoRequest, PurchaseRequest
from app.retrieval.embedders import HashingEmbedder
from app.retrieval.index import index_chunks
from app.services import audit
from app.services.ingest import ingest_document
from tests.integration.helpers import wipe_all

pytestmark = pytest.mark.integration
OUT = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "out"

REVIEWER = {"x-demo-role": "reviewer", "x-demo-user": "Rami Reviewer"}
FD = {**REVIEWER, "x-demo-authority": "finance director"}
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
    from app.db.session import get_session
    from app.main import create_app

    emb = HashingEmbedder()
    monkeypatch.setattr(a_api, "get_embedder", lambda: emb)
    monkeypatch.setattr(r_api, "get_embedder", lambda: emb)
    monkeypatch.setattr(get_settings(), "llm_provider", "mock")
    monkeypatch.setattr(get_settings(), "llm_api_key", None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def new_request(client, amount="12000.00", requester="Layla Hassan", **over):
    body = {"requester_name": requester, "department": "Finance", "currency": "USD", "supplier_name": "Orion Tech Supplies Ltd.",
            "justification": "Replacement of end-of-life finance team workstations before the audit season starts",
            "total_amount": amount, "submitted_on": "2026-03-10",
            "items": [{"description": "Laptop 14in business", "quantity": "10", "unit_cost": str(float(amount) / 10)}]}
    body.update(over)
    r = client.post("/requests", json=body)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def assess(client, rid):
    r = client.post(f"/requests/{rid}/assess", headers=REVIEWER)
    assert r.status_code == 201, r.text
    return r.json()


def decide(client, rid, action, aid=None, reasoning=REASON, reviews=None, headers=FD):
    body = {"action": action, "reasoning": reasoning, "finding_reviews": reviews or []}
    if aid:
        body["assessment_id"] = aid
    return client.post(f"/requests/{rid}/decisions", json=body, headers=headers)


def test_approval_workflow_enforces_every_rule_then_records_the_decision(db, client):
    rid = new_request(client)
    a = assess(client, rid)

    assert decide(client, rid, "approve", a["id"], headers={"x-demo-role": "requester", "x-demo-user": "Someone"}).status_code == 403
    r = decide(client, rid, "approve", a["id"], headers={"x-demo-role": "reviewer", "x-demo-user": "layla hassan"})
    assert r.status_code == 403 and "PRC-001:3.1" in r.json()["detail"]  # nobody decides their own request
    r = decide(client, rid, "approve", a["id"], headers=REVIEWER)  # default authority: procurement officer
    assert r.status_code == 403 and "finance director" in r.json()["detail"] and "PRC-001:2.3" in r.json()["detail"]
    assert decide(client, rid, "approve", a["id"], reasoning="ok").status_code == 422
    assert decide(client, rid, "approve", None).status_code == 409  # must name the assessment that was reviewed
    assert client.get(f"/requests/{rid}").json()["status"] == "assessed"  # nothing above changed the request

    r = decide(client, rid, "approve", a["id"])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["actor_type"] == "human" and d["reviewer"] == {"name": "Rami Reviewer", "role": "reviewer"}
    assert d["ai_recommendation_at_decision"]["version"] == 1 and d["ai_recommendation_at_decision"]["is_mock"]
    assert client.get(f"/requests/{rid}").json()["status"] == "approved"

    assert decide(client, rid, "reject", a["id"]).status_code == 409  # decisions are final
    assert decide(client, rid, "request_info").status_code == 409

    h = client.get(f"/requests/{rid}/history").json()
    assert [x["action"] for x in h["decisions"]] == ["approve"] and len(h["ai_assessments"]) == 1
    kinds = [(e["actor_type"], e["action"]) for e in h["timeline"]]
    assert ("ai", "assessment.created") in kinds and ("user", "decision.recorded") in kinds and ("user", "request.created") in kinds
    assert "only the decisions listed are human decisions" in h["note"]
    entries = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert audit.verify_chain(entries) == (True, None)


def test_the_database_itself_refuses_approval_without_a_decision(db, client):
    rid = new_request(client)
    assess(client, rid)
    with pytest.raises(DBAPIError, match="requires a matching human decision"), db.begin_nested():
        db.execute(text("update purchase_requests set status = 'approved' where id = :i"), {"i": rid})


def test_approving_over_a_confirmed_violation_needs_a_documented_override(db, client):
    rid = new_request(client, amount="800.00", justification="")  # no justification => confirmed violation (PRC-006:2.1)
    a = assess(client, rid)
    confirmed = [f for f in a["findings"] if f["category"] == "confirmed_violation"]
    assert confirmed and a["compliance_status"] == "issues_found"
    fid = confirmed[0]["id"]

    r = decide(client, rid, "approve", a["id"])
    assert r.status_code == 409 and confirmed[0]["title"] in r.json()["detail"]
    r = decide(client, rid, "approve", a["id"], reviews=[{"finding_id": fid, "verdict": "agree", "note": "It really is missing"}])
    assert r.status_code == 409
    assert client.get(f"/requests/{rid}").json()["status"] == "assessed"

    r = decide(client, rid, "approve", a["id"], reasoning="Requester confirmed the reason verbally; low value purchase.",
               reviews=[{"finding_id": fid, "verdict": "disagree", "note": "Justification supplied by phone, logged in the ticket"}])
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["went_against_ai_signal"] is True and d["ai_recommendation_at_decision"]["status"] == "issues_found"
    assert d["finding_reviews"][0]["verdict"] == "disagree" and d["finding_reviews"][0]["category"] == "confirmed_violation"
    assert db.execute(select(FindingReview)).scalars().first().note.startswith("Justification supplied")


def test_stale_assessment_is_refused_and_reject_needs_only_reasoning(db, client):
    rid = new_request(client)
    first = assess(client, rid)
    second = assess(client, rid)
    r = decide(client, rid, "reject", first["id"])
    assert r.status_code == 409 and "different assessment" in r.json()["detail"]
    r = decide(client, rid, "reject", second["id"], headers=REVIEWER)  # rejecting needs no approval level
    assert r.status_code == 201 and client.get(f"/requests/{rid}").json()["status"] == "rejected"
    assert r.json()["went_against_ai_signal"] is False


def test_information_request_loop(db, client):
    rid = new_request(client)
    assert client.post(f"/requests/{rid}/info-response", json={"message": "here you go"}).status_code == 409  # none open

    r = decide(client, rid, "request_info", reasoning="Please attach two more quotations from other suppliers.")
    assert r.status_code == 201  # asking needs no assessment
    assert client.get(f"/requests/{rid}").json()["status"] == "info_requested"
    assert db.execute(select(InfoRequest).where(InfoRequest.resolved_at.is_(None))).scalars().first()
    queue_ids = {q["id"] for q in client.get("/review/queue?status=info_requested", headers=REVIEWER).json()}
    assert rid in queue_ids and rid not in {q["id"] for q in client.get("/review/queue", headers=REVIEWER).json()}

    resp = client.post(f"/requests/{rid}/info-response", json={"message": "Two quotations attached."}, headers={"x-demo-user": "Layla Hassan"})
    assert resp.status_code == 200 and resp.json()["resolved_requests"] == 1
    assert client.get(f"/requests/{rid}").json()["status"] == "submitted"
    assert client.post(f"/requests/{rid}/info-response", json={"message": "again"}).status_code == 409
    h = client.get(f"/requests/{rid}/history").json()
    assert h["information_requests"][0]["resolved_at"] and h["decisions"][0]["action"] == "request_info"

    a = assess(client, rid)
    assert decide(client, rid, "reject", a["id"], reasoning="Still not enough quotations after the follow-up.").status_code == 201
    assert [d["action"] for d in client.get(f"/requests/{rid}/decisions").json()] == ["request_info", "reject"]
    # decisions made in one transaction are ordered by real insertion time, which the DB gate relies on
    assert db.execute(select(Decision).where(Decision.request_id == rid)).scalars().all()[-1].action.value == "reject"


def test_review_queue_is_reviewer_only_and_ordered_by_ai_risk_then_age(db, client):
    low = new_request(client, amount="800.00", requester="Alice A")
    high = new_request(client, amount="800.00", requester="Bob B", justification="")  # confirmed violation => higher risk
    unassessed = new_request(client, amount="900.00", requester="Cara C")
    assess(client, low)
    assess(client, high)
    assert client.get("/review/queue", headers={"x-demo-role": "requester"}).status_code == 403
    q = client.get("/review/queue", headers=REVIEWER).json()
    ids = [x["id"] for x in q]
    assert ids.index(high) < ids.index(low) < ids.index(unassessed)  # risk first, unassessed last
    row = next(x for x in q if x["id"] == high)
    assert row["latest_assessment"]["findings"]["confirmed_violation"] >= 1 and row["required_approval"]["authority"] == "department manager"
    assert next(x for x in q if x["id"] == unassessed)["needs_assessment"] is True
    assert db.execute(select(PurchaseRequest).where(PurchaseRequest.id == high)).scalar_one().status.value == "assessed"
