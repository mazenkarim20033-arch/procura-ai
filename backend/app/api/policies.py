from datetime import date
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.auth import CurrentUser, require_role
from app.config import get_settings
from app.db import enums as E
from app.db.models import Chunk, Policy
from app.db.session import get_session
from app.errors import NotFoundError
from app.retrieval.embedders import get_embedder
from app.retrieval.index import embedding_stats, index_chunks
from app.retrieval.search import SearchFilters, relevance_gate, search
from app.services import audit

router = APIRouter(prefix="/policies", tags=["policies"])


class SearchRequest(BaseModel):
    query: str = Field(min_length=3, max_length=1000)
    k: int = Field(default=6, ge=1, le=20)
    mode: Literal["dense", "fts", "hybrid"] | None = None  # default: settings.retrieval_mode
    as_of: date | None = None
    categories: list[str] | None = None


def _policy_row(p: Policy, chunks: int, embedded: int) -> dict:
    return {
        "id": str(p.id), "code": p.code, "title": p.title, "version": p.version, "category": p.category,
        "effective_from": p.effective_from.isoformat(),
        "effective_to": p.effective_to.isoformat() if p.effective_to else None,
        "status": p.status, "chunks": chunks, "embedded_chunks": embedded,
    }


@router.get("")
def list_policies(session: Session = Depends(get_session)) -> list[dict]:
    rows = session.execute(
        select(Policy, func.count(Chunk.id), func.count(Chunk.embedding))
        .outerjoin(Chunk, Chunk.policy_id == Policy.id).group_by(Policy.id).order_by(Policy.code)
    ).all()
    return [_policy_row(p, n, e) for p, n, e in rows]


@router.get("/{policy_id}")
def get_policy(policy_id: UUID, session: Session = Depends(get_session)) -> dict:
    policy = session.get(Policy, policy_id)
    if not policy:
        raise NotFoundError("Policy not found")
    chunks = session.execute(
        select(Chunk).where(Chunk.policy_id == policy.id).order_by(Chunk.page_start, Chunk.char_start)
    ).scalars().all()
    return {
        **_policy_row(policy, len(chunks), sum(c.embedding is not None for c in chunks)),
        "clauses": [{"id": str(c.id), "section_path": c.section_path, "text": c.text, "page": c.page_start}
                    for c in chunks],
    }


@router.post("/search")
def search_policies(body: SearchRequest, session: Session = Depends(get_session)) -> dict:
    """Debug/inspection endpoint: shows exactly what the assessment pipeline would retrieve."""
    settings = get_settings()
    filters = SearchFilters(as_of=body.as_of, categories=body.categories)
    result = search(session, body.query, get_embedder(), filters=filters, k=body.k,
                    mode=body.mode or settings.retrieval_mode)
    gate = relevance_gate(result, settings.relevance_min_similarity)
    return {
        "query": body.query, "mode": result.mode, "embedding_model": get_embedder().name,
        "relevance": {"relevant": gate.relevant, "best_similarity": gate.best_similarity, "reason": gate.reason,
                      "threshold": settings.relevance_min_similarity},
        "timings_ms": result.timings_ms,
        "hits": [{**h.as_log(), "text": h.text, "page": h.page_start} for h in result.hits],
    }


@router.post("/reindex")
def reindex(
    user: CurrentUser = Depends(require_role(E.Role.admin)), session: Session = Depends(get_session),
) -> dict:
    embedder = get_embedder()
    n = index_chunks(session, embedder)
    audit.append(session, actor_type="user", actor_id=user.name, action="policies.reindexed",
                 entity_type="chunk", payload={"embedded": n, "model": embedder.name})
    session.commit()
    return {"embedded_now": n, "model": embedder.name, **embedding_stats(session)}
