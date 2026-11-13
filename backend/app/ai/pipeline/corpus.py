"""PolicyCorpus implementations: in-memory (benchmarks, tests) and database-backed (production)."""
from datetime import date

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.pipeline.context import Clause, ClauseHit
from app.db.models import Chunk, Policy
from app.retrieval.base import Embedder
from app.retrieval.search import SearchFilters, search


def clause_ref(policy_code: str, section_path: str | None) -> str | None:
    """'PRC-002 > 1 Quotation Requirements > 1.3' (+ optional ' (part 2)') -> 'PRC-002:1.3'."""
    if not section_path:
        return None
    last = section_path.rsplit(">", 1)[-1].strip().split(" ")[0]
    return f"{policy_code}:{last}" if last[:1].isdigit() else None


class MemoryPolicyCorpus:
    def __init__(self, clauses: list[Clause], embedder: Embedder):
        self._clauses = {c.ref: c for c in clauses}
        self._embedder = embedder
        refs = list(self._clauses)
        vecs = np.array(embedder.embed_documents([f"[{r}] {self._clauses[r].text}" for r in refs]), dtype=float)
        self._refs = refs
        self._matrix = vecs / np.maximum(np.linalg.norm(vecs, axis=1, keepdims=True), 1e-12)

    def get(self, ref: str) -> Clause | None:
        return self._clauses.get(ref)

    def search(self, query: str, k: int) -> list[ClauseHit]:
        q = np.array(self._embedder.embed_query(query), dtype=float)
        q /= max(np.linalg.norm(q), 1e-12)
        sims = self._matrix @ q
        order = np.argsort(-sims)[:k]
        return [ClauseHit(self._clauses[self._refs[i]], float(sims[i])) for i in order]


class DbPolicyCorpus:
    """Clauses of active policies in force on `as_of`, read from the chunks table."""

    def __init__(self, session: Session, embedder: Embedder, as_of: date | None):
        self._s, self._embedder, self._as_of = session, embedder, as_of
        self.retrievals: list[dict] = []  # query logs for persistence

    def _in_force(self):
        conds = [Policy.status == "active"]
        if self._as_of:
            conds += [Policy.effective_from <= self._as_of,
                      (Policy.effective_to.is_(None)) | (Policy.effective_to >= self._as_of)]
        return conds

    def _to_clause(self, chunk: Chunk, code: str) -> Clause | None:
        ref = clause_ref(code, chunk.section_path)
        if ref is None:
            return None
        return Clause(ref, code, ref.split(":")[1], chunk.text, str(chunk.id), chunk.section_path)

    def get(self, ref: str) -> Clause | None:
        code, _, number = ref.partition(":")
        rows = self._s.execute(
            select(Chunk, Policy.code).join(Policy, Chunk.policy_id == Policy.id)
            .where(Policy.code == code, Chunk.section_path.like(f"%> {number}%"), *self._in_force())
            .order_by(Policy.effective_from.desc())
        ).all()
        for chunk, pcode in rows:
            clause = self._to_clause(chunk, pcode)
            if clause and clause.ref == ref:
                return clause
        return None

    def search(self, query: str, k: int) -> list[ClauseHit]:
        filters = SearchFilters(as_of=self._as_of)
        result = search(self._s, query, self._embedder, filters=filters, k=k, mode="dense")
        self.retrievals.append({"query": query, "filters": filters.as_json(),
                                "results": [h.as_log() for h in result.hits]})
        hits = []
        for h in result.hits:
            ref = clause_ref(h.policy_code or "", h.section_path)
            if ref and h.dense_similarity is not None:
                hits.append(ClauseHit(Clause(ref, h.policy_code or "", ref.split(":")[1], h.text, h.chunk_id,
                                             h.section_path), h.dense_similarity))
        return hits
