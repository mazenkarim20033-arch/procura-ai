"""Full assessment flow against the live database (rolled back), mock LLM, hashing embedder."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.pipeline.core import AssessmentResult
from app.config import get_settings
from app.db.models import (
    Assessment,
    AuditLog,
    Finding,
    FindingEvidence,
    LlmCall,
    PurchaseRequest,
    RetrievalLog,
)
from app.retrieval.embedders import HashingEmbedder
from app.retrieval.index import index_chunks
from app.rules.policy_rules import Evidence, RuleFinding
from app.services import assessment as svc
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
    monkeypatch.setattr(get_settings(), "llm_stage_min_similarity", -1.0)  # let the LLM stage run with hashing vectors
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    return TestClient(app)


def deal(db, client, deal_id: str, headers=None) -> str:
    """Ingest a deal's request + quotations, create the request, attach quotes; return request id."""
    pr = next((OUT / "purchase_requests").glob(f"purchase_request_{deal_id}.pdf"))
    rid = client.post(f"/requests/from-document/{ingest_document(db, filename=pr.name, data=pr.read_bytes(), mime='application/pdf').document.id}").json()["id"]
    for q in sorted((OUT / "quotations").glob(f"quotation_{deal_id}_*.pdf")):
        d = ingest_document(db, filename=q.name, data=q.read_bytes(), mime="application/pdf").document
        assert client.post(f"/requests/{rid}/documents", json={"document_id": str(d.id)}).status_code == 201
    return rid


def test_assess_endpoint_persists_findings_with_evidence_and_never_approves(db, client):
    rid = deal(db, client, "D01")
    reviewer = {"x-demo-role": "reviewer", "x-demo-user": "rev"}
    assert client.post(f"/requests/{rid}/assess", headers={"x-demo-role": "requester"}).status_code == 403

    r = client.post(f"/requests/{rid}/assess", headers=reviewer)
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["version"] == 1 and a["is_mock"] and a["provider"] == "mock"
    assert a["compliance_status"] in {"issues_found", "needs_information", "inconclusive", "no_issues_found"}
    assert a["findings"] and "human procurement officer" in a["decision_required"]
    assert a["prompt_versions"]["clause_reasoning"] == "clause_reasoning@v2"
    for f in a["findings"]:
        if f["category"] != "inconclusive":
            assert f["evidence"], f
        for e in f["evidence"]:
            if e["kind"] == "policy_chunk":
                assert e["chunk_id"] and e["quote"]
        if f["category"] == "confirmed_violation":
            assert f["source"] == "rule"

    req = db.get(PurchaseRequest, rid) or db.execute(select(PurchaseRequest).where(PurchaseRequest.id == rid)).scalar_one()
    assert req.status.value == "assessed"  # assessed, never approved/rejected
    assert db.execute(select(LlmCall).where(LlmCall.assessment_id == a["id"])).scalars().first().status == "ok"
    assert db.execute(select(RetrievalLog).where(RetrievalLog.assessment_id == a["id"])).scalars().first()

    second = client.post(f"/requests/{rid}/assess", headers=reviewer).json()
    assert second["version"] == 2
    assert [x["version"] for x in client.get(f"/requests/{rid}/assessments").json()] == [2, 1]
    assert client.get(f"/assessments/{a['id']}").json()["id"] == a["id"]

    entries = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert audit.verify_chain(entries) == (True, None)
    ai_entries = [e for e in entries if e.action == "assessment.created"]
    assert len(ai_entries) == 2 and ai_entries[0].actor_type == "ai" and ai_entries[0].payload_json["triggered_by"] == "rev"


def test_approved_supplier_setting_drives_the_rule(db, client):
    rid = deal(db, client, "D01")
    admin, reviewer = {"x-demo-role": "admin"}, {"x-demo-role": "reviewer"}
    assert client.get("/settings/approved-suppliers").json() == {"configured": False, "names": []}
    assert client.put("/settings/approved-suppliers", json={"names": ["X"]}, headers=reviewer).status_code == 403

    # Without a list, the >5,000 rule cannot judge (if this deal is above 5,000) and says so.
    before = client.post(f"/requests/{rid}/assess", headers=reviewer).json()
    codes = {f["rule_code"]: f["category"] for f in before["findings"]}
    if "R-SUPPLIER-APPROVED" in codes:
        assert codes["R-SUPPLIER-APPROVED"] == "missing_information"

    req = db.execute(select(PurchaseRequest).where(PurchaseRequest.id == rid)).scalar_one()
    assert client.put("/settings/approved-suppliers", json={"names": ["Nobody Ltd"]}, headers=admin).json()["configured"]
    after = client.post(f"/requests/{rid}/assess", headers=reviewer).json()
    codes = {f["rule_code"]: f["category"] for f in after["findings"]}
    if req.total_amount and req.total_amount > 5000 and req.currency == "USD":
        assert codes["R-SUPPLIER-APPROVED"] == "confirmed_violation"
    else:
        assert "R-SUPPLIER-APPROVED" not in codes


def test_persist_guard_rejects_findings_without_evidence(db):
    req = PurchaseRequest(request_no="G-1")
    db.add(req)
    db.flush()
    bad = AssessmentResult(
        overall_risk="low", compliance_status="inconclusive", confidence=0.5, summary="s",
        findings=[RuleFinding("X", "potential_violation", "t", "e", [])], missing_info=[], financial_risks=[],
        next_steps=[], counts={}, checks_run=[])
    with pytest.raises(ValueError, match="no evidence"):
        svc.persist_assessment(db, req, bad, [], actor="t")
    no_chunk = AssessmentResult(
        overall_risk="low", compliance_status="inconclusive", confidence=0.5, summary="s",
        findings=[RuleFinding("X", "potential_violation", "t", "e", [Evidence("policy_chunk", "q", None, "PRC-001:1.1")])],
        missing_info=[], financial_risks=[], next_steps=[], counts={}, checks_run=[])
    with pytest.raises(ValueError, match="chunk id"):
        svc.persist_assessment(db, req, no_chunk, [], actor="t")
    assert db.execute(select(Assessment).where(Assessment.request_id == req.id)).first() is None


def test_db_findings_table_rejects_llm_confirmed_violations(db):
    from sqlalchemy.exc import IntegrityError

    req = PurchaseRequest(request_no="G-2")
    db.add(req)
    db.flush()
    result = AssessmentResult(overall_risk="low", compliance_status="inconclusive", confidence=0.5, summary="s",
                              findings=[], missing_info=[], financial_risks=[], next_steps=[], counts={}, checks_run=[])
    a = svc.persist_assessment(db, req, result, [], actor="t")
    with pytest.raises(IntegrityError), db.begin_nested():
        db.add(Finding(assessment_id=a.id, category="confirmed_violation", source="llm", title="x", explanation="y"))
        db.flush()
    assert json.dumps(a.prompt_versions_json) == "{}"
    assert db.execute(select(FindingEvidence)).first() is None
