"""Provider-neutral retrieval interfaces. Implementations are chosen by config, so models can be
swapped without touching callers (contract tests run against every implementation)."""
from dataclasses import dataclass, field
from typing import Protocol


class Embedder(Protocol):
    name: str
    dim: int

    def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    def embed_query(self, text: str) -> list[float]: ...


class Reranker(Protocol):
    name: str

    def rerank(self, query: str, texts: list[str]) -> list[float]:
        """Return one relevance score per text (higher = more relevant)."""
        ...


@dataclass
class SearchHit:
    chunk_id: str
    policy_code: str | None
    section_path: str | None
    text: str
    page_start: int | None = None
    dense_similarity: float | None = None  # cosine similarity (1 - cosine distance)
    dense_rank: int | None = None
    fts_rank: int | None = None
    fts_score: float | None = None
    rrf_score: float = 0.0
    rerank_score: float | None = None
    scores: dict = field(default_factory=dict)

    def as_log(self) -> dict:
        return {
            "chunk_id": self.chunk_id, "policy_code": self.policy_code, "section_path": self.section_path,
            "dense_similarity": self.dense_similarity, "dense_rank": self.dense_rank,
            "fts_rank": self.fts_rank, "rrf_score": self.rrf_score, "rerank_score": self.rerank_score,
        }
