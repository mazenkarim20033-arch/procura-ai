import math
import sys
from pathlib import Path

import pytest

from app.config import Settings
from app.retrieval.base import SearchHit
from app.retrieval.embedders import HashingEmbedder, build_embedder
from app.retrieval.search import (
    RRF_K,
    SearchFilters,
    SearchResult,
    fts_query_string,
    relevance_gate,
    rrf_fuse,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "evals"))
import metrics as M


def test_rrf_rewards_agreement_between_rankings():
    scores = rrf_fuse([["a", "b", "c"], ["c", "b", "d"]])
    assert scores["b"] == pytest.approx(1 / (RRF_K + 2) + 1 / (RRF_K + 2))
    assert scores["a"] == pytest.approx(1 / (RRF_K + 1))
    assert max(scores, key=scores.get) in {"b", "c"}  # appears high in both lists
    assert scores["d"] < scores["b"]
    assert rrf_fuse([[], []]) == {}


def test_fts_query_is_or_of_unique_terms():
    assert fts_query_string("Who approves USD 7,500 monitors? Who?") == "who | approves | usd | 500 | monitors"
    assert fts_query_string("?! a") is None
    assert fts_query_string("") is None


def test_hashing_embedder_is_deterministic_unit_length_and_labelled_test_only():
    e = HashingEmbedder(384)
    a, b = e.embed_query("approval limit for laptops"), e.embed_query("approval limit for laptops")
    assert a == b and len(a) == 384
    assert math.isclose(sum(x * x for x in a), 1.0, rel_tol=1e-9)
    assert "test-only" in e.name


def test_embedder_factory_and_unknown_provider():
    assert build_embedder(Settings(embedding_provider="hashing", _env_file=None)).name == "hashing-test-only"
    fe = build_embedder(Settings(embedding_provider="fastembed", _env_file=None))
    assert fe.name == "sentence-transformers/all-MiniLM-L6-v2" and not fe.loaded  # constructing must not load the model
    with pytest.raises(ValueError):
        build_embedder(Settings(embedding_provider="nope", _env_file=None))


def _result(sim: float | None, n_hits: int = 1) -> SearchResult:
    hits = [SearchHit("c1", "PRC-001", "p", "t", dense_similarity=sim) for _ in range(n_hits)]
    return SearchResult(hits, "hybrid", sim)


def test_relevance_gate_decisions():
    assert relevance_gate(_result(0.7), 0.5).relevant
    low = relevance_gate(_result(0.3), 0.5)
    assert not low.relevant and "below threshold" in low.reason
    assert not relevance_gate(_result(None, n_hits=0), 0.5).relevant
    assert "no candidate" in relevance_gate(_result(None, n_hits=0), 0.5).reason
    assert not relevance_gate(_result(None), 0.5).relevant  # hits but no similarity => cannot vouch


def test_filters_serialise_for_logging():
    from datetime import date

    f = SearchFilters(as_of=date(2026, 1, 1), categories=["it"])
    assert f.as_json() == {"as_of": "2026-01-01", "categories": ["it"], "policy_codes": None}


def test_ranking_metrics():
    ranked = ["x", "a", "y", "b", "z"]
    rel = {"a", "b", "missing"}
    assert M.precision_at_k(ranked, rel, 2) == 0.5
    assert M.precision_at_k(ranked, rel, 5) == pytest.approx(0.4)
    assert M.recall_at_k(ranked, rel, 5) == pytest.approx(2 / 3)
    assert M.reciprocal_rank(ranked, rel) == 0.5
    assert M.reciprocal_rank(["q"], rel) == 0.0
    # perfect ordering of a 2-item relevant set gives nDCG 1.0
    assert M.ndcg_at_k(["a", "b", "x"], {"a", "b"}, 3) == pytest.approx(1.0)
    assert M.ndcg_at_k(["x", "a", "b"], {"a", "b"}, 3) < 1.0
    with pytest.raises(ValueError):
        M.recall_at_k(ranked, set(), 3)
    assert M.percentile([1, 2, 3, 4, 100], 50) == 3
