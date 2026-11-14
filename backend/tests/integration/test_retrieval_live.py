"""Hybrid retrieval against the live database using the non-semantic hashing embedder
(no model download). Verifies SQL, filters, fusion and the API wiring, NOT retrieval quality;
quality is measured by evals/runners/retrieval.py with real models."""
from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import AuditLog, Chunk, Document, Policy
from app.retrieval.embedders import HashingEmbedder
from app.retrieval.index import embedding_stats, index_chunks
from app.retrieval.search import SearchFilters, log_retrieval, relevance_gate, search
from app.services.ingest import ingest_document
from tests.integration.helpers import wipe_all

pytestmark = pytest.mark.integration
POLICIES = Path(__file__).resolve().parents[3] / "data" / "synthetic" / "out" / "policies"


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
    for pdf in sorted(POLICIES.glob("*.pdf")):
        ingest_document(session, filename=pdf.name, data=pdf.read_bytes(), mime="application/pdf")
    yield session
    session.close()
    trans.rollback()
    conn.close()


def test_index_marks_documents_indexed_and_is_incremental(db):
    emb = HashingEmbedder()
    assert embedding_stats(db)["embedded"] == 0
    assert index_chunks(db, emb) == 45
    stats = embedding_stats(db)
    assert stats == {"chunks": 45, "embedded": 45, "models": ["hashing-test-only"]}
    assert all(d.status.value == "indexed" for d in db.execute(select(Document)).scalars())
    assert index_chunks(db, emb) == 0  # nothing left to do
    assert index_chunks(db, emb, reindex=True) == 45


def test_lexical_and_hybrid_search_find_the_obvious_clause(db):
    emb = HashingEmbedder()
    index_chunks(db, emb)
    q = "three written quotations suppliers purchases above USD 5,000"
    for mode in ("fts", "dense", "hybrid"):
        res = search(db, q, emb, k=5, mode=mode)
        assert res.hits, mode
        assert any(h.policy_code == "PRC-002" and h.section_path.endswith("1.3") for h in res.hits), mode
    hybrid = search(db, q, emb, k=3, mode="hybrid")
    assert hybrid.hits[0].rrf_score >= hybrid.hits[-1].rrf_score
    assert hybrid.hits[0].dense_similarity is not None and hybrid.best_similarity is not None
    assert set(hybrid.timings_ms) >= {"embed_query", "dense", "fts"}


def test_metadata_filters(db):
    emb = HashingEmbedder()
    index_chunks(db, emb)
    only_it = search(db, "software licence review", emb, k=10, filters=SearchFilters(categories=["it"]))
    assert only_it.hits and {h.policy_code for h in only_it.hits} == {"PRC-004"}
    coded = search(db, "payment terms", emb, k=10, filters=SearchFilters(policy_codes=["PRC-005"]))
    assert {h.policy_code for h in coded.hits} == {"PRC-005"}
    # PRC-006 takes effect 2025-06-01: before that date its clauses must not be retrievable.
    before = search(db, "emergency purchases", emb, k=10, filters=SearchFilters(as_of=date(2025, 3, 1)))
    assert "PRC-006" not in {h.policy_code for h in before.hits}
    after = search(db, "emergency purchases", emb, k=10, filters=SearchFilters(as_of=date(2026, 1, 1)))
    assert "PRC-006" in {h.policy_code for h in after.hits}
    # superseded/inactive policies are excluded
    db.execute(Policy.__table__.update().where(Policy.code == "PRC-006").values(status="superseded"))
    gone = search(db, "emergency purchases", emb, k=10)
    assert "PRC-006" not in {h.policy_code for h in gone.hits}


def test_hybrid_without_embeddings_degrades_to_lexical_and_gate_refuses(db):
    emb = HashingEmbedder()  # nothing indexed yet: no embeddings exist
    res = search(db, "emergency purchases quotations", emb, k=5, mode="hybrid")
    assert res.hits and all(h.dense_rank is None for h in res.hits)
    gate = relevance_gate(res, 0.0)
    assert not gate.relevant  # lexical hits alone cannot vouch for relevance


def test_retrieval_log_roundtrip(db):
    emb = HashingEmbedder()
    index_chunks(db, emb)
    res = search(db, "approval for monitors", emb, k=3)
    row = log_retrieval(db, None, "approval for monitors", SearchFilters(), res)
    assert row.results_json[0]["chunk_id"] == res.hits[0].chunk_id


def test_policy_api_list_detail_search_and_reindex_permissions(db, monkeypatch):
    from app.api import policies as policies_api
    from app.db.session import get_session
    from app.main import create_app
    from app.retrieval import embedders

    emb = HashingEmbedder()
    monkeypatch.setattr(policies_api, "get_embedder", lambda: emb)
    monkeypatch.setattr(embedders, "get_embedder", lambda: emb)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: db
    c = TestClient(app)

    listing = c.get("/policies").json()
    assert [p["code"] for p in listing] == [f"PRC-00{i}" for i in range(1, 7)]
    assert sum(p["chunks"] for p in listing) == 45 and sum(p["embedded_chunks"] for p in listing) == 0

    assert c.post("/policies/reindex", headers={"x-demo-role": "reviewer"}).status_code == 403
    done = c.post("/policies/reindex", headers={"x-demo-role": "admin"})
    assert done.status_code == 200 and done.json()["embedded_now"] == 45

    detail = c.get(f"/policies/{listing[1]['id']}").json()
    assert len(detail["clauses"]) == 9 and detail["clauses"][0]["section_path"].startswith("PRC-002")

    r = c.post("/policies/search", json={"query": "who approves large purchases", "k": 3})
    body = r.json()
    assert r.status_code == 200 and len(body["hits"]) == 3 and "relevance" in body
    assert body["embedding_model"] == "hashing-test-only"
    assert c.post("/policies/search", json={"query": "x"}).status_code == 422

    assert db.execute(select(AuditLog).where(AuditLog.action == "policies.reindexed")).scalars().first()
    assert db.execute(select(Chunk).where(Chunk.embedding.is_(None))).first() is None
    assert c.get("/policies/00000000-0000-0000-0000-000000000000").status_code == 404
