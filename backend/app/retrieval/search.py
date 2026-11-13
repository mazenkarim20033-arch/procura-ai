"""Hybrid retrieval over policy chunks: dense (pgvector cosine) + lexical (Postgres FTS), fused with
Reciprocal Rank Fusion, filtered by policy metadata, optionally reranked, then gated for relevance."""
import re
import time
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.db.models import Chunk, Policy, RetrievalLog
from app.retrieval.base import Embedder, Reranker, SearchHit

RRF_K = 60


@dataclass
class SearchFilters:
    as_of: date | None = None  # only policies in force on this date
    categories: list[str] | None = None
    policy_codes: list[str] | None = None

    def as_json(self) -> dict:
        return {"as_of": self.as_of.isoformat() if self.as_of else None,
                "categories": self.categories, "policy_codes": self.policy_codes}


@dataclass
class SearchResult:
    hits: list[SearchHit]
    mode: str
    best_similarity: float | None
    timings_ms: dict = field(default_factory=dict)


def _conditions(f: SearchFilters | None) -> list:
    conds = [Chunk.policy_id.is_not(None), Policy.status == "active"]
    if f is None:
        return conds
    if f.as_of:
        conds += [Policy.effective_from <= f.as_of, or_(Policy.effective_to.is_(None), Policy.effective_to >= f.as_of)]
    if f.categories:
        conds.append(Policy.category.in_(f.categories))
    if f.policy_codes:
        conds.append(Policy.code.in_(f.policy_codes))
    return conds


def fts_query_string(query: str) -> str | None:
    """OR-of-terms tsquery text. Natural-language questions rarely contain every term, so AND would
    return nothing; ts_rank_cd then orders by how many terms match."""
    tokens = list(dict.fromkeys(t for t in re.findall(r"[a-z0-9]+", query.lower()) if len(t) > 1))
    return " | ".join(tokens) if tokens else None


def rrf_fuse(rankings: list[list[str]], k: int = RRF_K) -> dict[str, float]:
    """Reciprocal Rank Fusion: score(d) = sum over rankings of 1 / (k + rank), rank starting at 1."""
    scores: dict[str, float] = {}
    for ranking in rankings:
        for rank, doc_id in enumerate(ranking, start=1):
            scores[doc_id] = scores.get(doc_id, 0.0) + 1.0 / (k + rank)
    return scores


def _hit(chunk: Chunk, policy: Policy) -> SearchHit:
    return SearchHit(chunk_id=str(chunk.id), policy_code=policy.code, section_path=chunk.section_path,
                     text=chunk.text, page_start=chunk.page_start)


def dense_search(session: Session, qvec: list[float], filters: SearchFilters | None, n: int):
    dist = Chunk.embedding.cosine_distance(qvec)
    q = (select(Chunk, Policy, dist).join(Policy, Chunk.policy_id == Policy.id)
         .where(Chunk.embedding.is_not(None), *_conditions(filters)).order_by(dist).limit(n))
    return session.execute(q).all()


def fts_search(session: Session, query: str, qvec: list[float] | None, filters: SearchFilters | None, n: int):
    qs = fts_query_string(query)
    if not qs:
        return []
    tsq = func.to_tsquery("english", qs)
    rank = func.ts_rank_cd(Chunk.tsv, tsq)
    cols = [Chunk, Policy, rank]
    if qvec is not None:
        cols.append(Chunk.embedding.cosine_distance(qvec))
    q = (select(*cols).join(Policy, Chunk.policy_id == Policy.id)
         .where(Chunk.tsv.op("@@")(tsq), *_conditions(filters)).order_by(rank.desc()).limit(n))
    return session.execute(q).all()


def search(
    session: Session, query: str, embedder: Embedder | None, *, filters: SearchFilters | None = None,
    k: int = 6, mode: str = "hybrid", dense_n: int = 30, fts_n: int = 30,
    reranker: Reranker | None = None, rerank_n: int = 20,
) -> SearchResult:
    if mode not in {"dense", "fts", "hybrid"}:
        raise ValueError(f"unknown mode {mode}")
    timings: dict[str, float] = {}
    hits: dict[str, SearchHit] = {}
    t0 = time.perf_counter()
    qvec = embedder.embed_query(query) if mode in {"dense", "hybrid"} and embedder else None
    timings["embed_query"] = round((time.perf_counter() - t0) * 1000, 1)

    dense_ids: list[str] = []
    fts_ids: list[str] = []
    t0 = time.perf_counter()
    if qvec is not None:
        for rank, (chunk, policy, dist) in enumerate(dense_search(session, qvec, filters, dense_n), start=1):
            h = hits.setdefault(str(chunk.id), _hit(chunk, policy))
            h.dense_rank, h.dense_similarity = rank, round(1.0 - float(dist), 4)
            dense_ids.append(str(chunk.id))
    timings["dense"] = round((time.perf_counter() - t0) * 1000, 1)

    t0 = time.perf_counter()
    if mode in {"fts", "hybrid"}:
        for rank, row in enumerate(fts_search(session, query, qvec, filters, fts_n), start=1):
            chunk, policy, score = row[0], row[1], row[2]
            h = hits.setdefault(str(chunk.id), _hit(chunk, policy))
            h.fts_rank, h.fts_score = rank, float(score)
            if len(row) > 3 and row[3] is not None and h.dense_similarity is None:
                h.dense_similarity = round(1.0 - float(row[3]), 4)
            fts_ids.append(str(chunk.id))
    timings["fts"] = round((time.perf_counter() - t0) * 1000, 1)

    rankings = {"dense": [dense_ids], "fts": [fts_ids], "hybrid": [dense_ids, fts_ids]}[mode]
    fused = rrf_fuse(rankings)
    for cid, score in fused.items():
        hits[cid].rrf_score = round(score, 6)
    ordered = sorted(hits.values(), key=lambda h: (-h.rrf_score, h.chunk_id))

    if reranker is not None and ordered:
        t0 = time.perf_counter()
        pool = ordered[:rerank_n]
        for h, s in zip(pool, reranker.rerank(query, [h.text for h in pool]), strict=True):
            h.rerank_score = float(s)
        ordered = sorted(pool, key=lambda h: -(h.rerank_score or 0.0))
        timings["rerank"] = round((time.perf_counter() - t0) * 1000, 1)

    top = ordered[:k]
    sims = [h.dense_similarity for h in top if h.dense_similarity is not None]
    return SearchResult(top, mode, max(sims) if sims else None, timings)


@dataclass
class Relevance:
    relevant: bool
    best_similarity: float | None
    reason: str


def relevance_gate(result: SearchResult, min_similarity: float) -> Relevance:
    """Context relevance check. If it fails, the assessment pipeline must report 'inconclusive'
    for this topic instead of asking an LLM to reason over unrelated text."""
    if not result.hits:
        return Relevance(False, None, "no candidate policy clauses retrieved")
    if result.best_similarity is None:
        return Relevance(False, None, "no dense similarity available for the retrieved clauses")
    if result.best_similarity < min_similarity:
        return Relevance(False, result.best_similarity,
                         f"best similarity {result.best_similarity:.3f} below threshold {min_similarity:.3f}")
    return Relevance(True, result.best_similarity, "ok")


def log_retrieval(session: Session, assessment_id, query: str, filters: SearchFilters | None,
                  result: SearchResult) -> RetrievalLog:
    row = RetrievalLog(
        assessment_id=assessment_id, query=query, filters_json=filters.as_json() if filters else {},
        results_json=[h.as_log() for h in result.hits], reranked=any(h.rerank_score is not None for h in result.hits),
    )
    session.add(row)
    session.flush()
    return row
