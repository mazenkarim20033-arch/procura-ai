"""Runs against the real Supabase database inside a transaction that is always rolled back.
Skipped automatically when DATABASE_URL is not configured."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditLog, Chunk, Document, Extraction, Policy
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


def pdf(sub: str, prefix: str) -> tuple[str, bytes]:
    f = min((OUT / sub).glob(f"{prefix}*.pdf"))
    return f.name, f.read_bytes()


def test_policy_ingest_creates_policy_clauses_and_extraction(db):
    name, data = pdf("policies", "policy_prc-002")
    r = ingest_document(db, filename=name, data=data, mime="application/pdf", is_synthetic=True)
    assert r.created and r.document.doc_type.value == "policy"
    assert r.policy is not None and r.policy.code == "PRC-002" and r.policy.version == "2.1"
    chunks = db.execute(select(Chunk).where(Chunk.document_id == r.document.id)).scalars().all()
    assert len(chunks) == 9 and all(c.policy_id == r.policy.id for c in chunks)
    assert any(c.text.startswith("Purchases above USD 5,000 and up to USD 25,000") for c in chunks)
    assert chunks[0].embedding is None  # embeddings arrive in the RAG milestone
    assert db.execute(select(Extraction).where(Extraction.document_id == r.document.id)).scalar_one()


def test_quotation_ingest_flags_problems_and_dedupes(db):
    # D03 quotation set includes an injected arithmetic flaw somewhere; ingest all and look for it.
    codes = set()
    for f in sorted((OUT / "quotations").glob("*.pdf")):
        r = ingest_document(db, filename=f.name, data=f.read_bytes(), mime="application/pdf", is_synthetic=True)
        codes |= {i.code for i in r.issues}
    assert {"line_total_mismatch", "subtotal_mismatch", "total_mismatch", "missing_optional"} <= codes

    f = min((OUT / "quotations").glob("*.pdf"))
    again = ingest_document(db, filename=f.name, data=f.read_bytes(), mime="application/pdf")
    assert again.created is False
    assert db.execute(select(Document).where(Document.sha256 == again.document.sha256)).scalar_one()


def test_audit_chain_on_live_database(db):
    audit.append(db, actor_type="system", actor_id=None, action="t1", entity_type="test", payload={"a": 1})
    audit.append(db, actor_type="user", actor_id="u", action="t2", entity_type="test", payload={"b": [1, 2]})
    rows = db.execute(select(AuditLog).order_by(AuditLog.id)).scalars().all()
    assert audit.verify_chain(rows) == (True, None)


def test_upload_api_permissions_and_flow(db, monkeypatch, tmp_path):
    from app.api import documents as docs_api
    from app.db.session import get_session
    from app.main import create_app

    monkeypatch.setattr(docs_api, "STORAGE_DIR", tmp_path)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    c = TestClient(app)

    pname, pdata = pdf("policies", "policy_prc-001")
    denied = c.post("/documents", files={"file": (pname, pdata, "application/pdf")}, headers={"x-demo-role": "requester"})
    assert denied.status_code == 403
    assert db.execute(select(Policy).where(Policy.code == "PRC-001")).first() is None
    assert not list(tmp_path.iterdir())  # stored file removed on denial

    ok = c.post("/documents", files={"file": (pname, pdata, "application/pdf")}, headers={"x-demo-role": "admin"})
    assert ok.status_code == 201 and ok.json()["doc_type"] == "policy" and ok.json()["chunk_count"] == 9

    qname, qdata = pdf("quotations", "quotation_D01")
    up = c.post("/documents", files={"file": (qname, qdata, "application/pdf")}, headers={"x-demo-role": "requester"})
    assert up.status_code == 201 and up.json()["doc_type"] == "quotation"
    detail = c.get(f"/documents/{up.json()['id']}").json()
    assert detail["extraction"]["data"]["vendor_name"] and detail["extraction"]["provenance"]["vendor_name"]["page"] == 1

    bad = c.post("/documents", files={"file": ("x.png", b"\x89PNG", "image/png")})
    assert bad.status_code == 422 and bad.json()["title"] == "unsupported_document"
    assert c.get("/documents/00000000-0000-0000-0000-000000000000").status_code == 404

    entries = db.execute(select(AuditLog).where(AuditLog.action == "document.uploaded")).scalars().all()
    assert len(entries) == 2
    assert db.execute(text("select count(*) from documents")).scalar() >= 2
