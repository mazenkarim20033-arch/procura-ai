"""Regression guard for the compliance benchmark (rules-only and mock modes) using non-semantic hashing
vectors, so no model download is needed. Not evidence of real-world accuracy."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "evals" / "runners"))
sys.path.insert(0, str(ROOT / "evals"))

import compliance as bench
from synthetic_corpus import load_clauses

from app.ai.pipeline.corpus import MemoryPolicyCorpus
from app.ai.providers.mock import MockProvider
from app.retrieval.embedders import HashingEmbedder


@pytest.fixture(scope="module")
def scenarios():
    return json.loads(bench.SCENARIOS.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def corpus():
    return MemoryPolicyCorpus(load_clauses(), HashingEmbedder())


def test_dataset_shape(scenarios):
    assert len(scenarios) == 40 and len({s["id"] for s in scenarios}) == 40
    assert {s["category"] for s in scenarios} == {"compliant", "violation", "missing", "ambiguous", "adversarial"}


def test_rules_only_matches_gold(scenarios, corpus):
    r = bench.run_mode("none", None, scenarios, corpus, -1.0)
    assert r["failures"] == [], r["failures"][:3]
    assert r["micro"]["f1"] == 1.0 and r["status_accuracy"] == 1.0
    assert r["false_approval_rate"]["value"] == 0.0
    assert r["invariant_violations"] == 0


def test_full_pipeline_with_mock_keeps_invariants(scenarios, corpus):
    r = bench.run_mode("mock", MockProvider(), scenarios, corpus, -1.0)
    assert r["invariant_violations"] == 0
    assert r["false_approval_rate"]["value"] == 0.0
    assert r["per_category"]["confirmed_violation"]["recall"] == 1.0  # LLM stage never hides rule findings
    assert r["status_accuracy"] is None  # intentionally not scored when an LLM stage runs
