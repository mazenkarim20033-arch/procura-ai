"""Retrieval benchmark: dense vs FTS vs hybrid (RRF) vs hybrid+rerank, several embedding models,
plus relevance-gate threshold tuning on the dev split and evaluation on the held-out test split.

    cd backend && .venv/Scripts/python ../evals/runners/retrieval.py [--no-rerank] [--models a,b]

Needs DATABASE_URL (everything runs inside a transaction that is rolled back) and downloads
embedding models on first use. Writes evals/reports/retrieval_<date>_<sha>.json.
Corpus: the 6 synthetic policies (45 clauses). Queries: evals/datasets/retrieval_queries.json
(frozen before tuning). Results are on synthetic data and do not generalise to real policies.
"""
import argparse
import hashlib
import json
import statistics
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals"))

import metrics as M
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.models import Chunk, Policy
from app.db.session import get_engine
from app.retrieval.embedders import FastEmbedEmbedder
from app.retrieval.index import index_chunks
from app.retrieval.rerank import FastEmbedReranker
from app.retrieval.search import search
from app.services.ingest import ingest_document

POLICIES_DIR = ROOT / "data" / "synthetic" / "out" / "policies"
QUERIES = ROOT / "evals" / "datasets" / "retrieval_queries.json"
REPORTS = ROOT / "evals" / "reports"
KS = (1, 3, 5, 10)
DEFAULT_MODELS = ["BAAI/bge-small-en-v1.5", "sentence-transformers/all-MiniLM-L6-v2"]


def split_of(query_id: str) -> str:
    return "dev" if int(hashlib.sha1(query_id.encode()).hexdigest(), 16) % 10 < 6 else "test"


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def ref_of(chunk: Chunk, policy_code: str) -> str:
    return f"P{policy_code[-1]}-{chunk.section_path.rsplit('>', 1)[-1].strip().split(' ')[0]}"


def summarize(rows: list[dict]) -> dict:
    pos = [r for r in rows if r["relevant"]]
    out = {"n": len(pos), "mrr": round(statistics.mean(r["rr"] for r in pos), 4)}
    for k in KS:
        out[f"P@{k}"] = round(statistics.mean(r[f"P@{k}"] for r in pos), 4)
        out[f"R@{k}"] = round(statistics.mean(r[f"R@{k}"] for r in pos), 4)
    out["nDCG@10"] = round(statistics.mean(r["ndcg10"] for r in pos), 4)
    return out


def tune_gate(rows) -> dict:
    """Pick the similarity threshold maximising balanced accuracy on the DEV split only."""
    dev = [r for r in rows if r["split"] == "dev" and r["best_similarity"] is not None]
    pos = [r["best_similarity"] for r in dev if r["relevant"]]
    neg = [r["best_similarity"] for r in dev if not r["relevant"]]
    if not pos or not neg:
        return {"threshold": None}
    best = (-1.0, None)
    for t in sorted(set(pos + neg)):
        tpr = sum(s >= t for s in pos) / len(pos)
        tnr = sum(s < t for s in neg) / len(neg)
        if (tpr + tnr) / 2 > best[0]:
            best = ((tpr + tnr) / 2, t)
    return {"threshold": best[1], "dev_balanced_accuracy": round(best[0], 4)}


def gate_eval(rows, threshold) -> dict:
    out = {}
    for split in ("dev", "test"):
        part = [r for r in rows if r["split"] == split and r["best_similarity"] is not None]
        pos = [r for r in part if r["relevant"]]
        neg = [r for r in part if not r["relevant"]]
        out[split] = {
            "positives_passed": round(sum(r["best_similarity"] >= threshold for r in pos) / len(pos), 4) if pos else None,
            "negatives_rejected": round(sum(r["best_similarity"] < threshold for r in neg) / len(neg), 4) if neg else None,
            "n_pos": len(pos), "n_neg": len(neg),
        }
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--models", default=",".join(DEFAULT_MODELS))
    args = ap.parse_args()
    if not get_settings().database_url:
        sys.exit("DATABASE_URL not configured")

    queries = json.loads(QUERIES.read_text(encoding="utf-8"))
    conn = get_engine().connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    report = {"run_date": date.today().isoformat(), "git_sha": git_sha(), "configs": {},
              "dataset": {"queries": len(queries), "positives": sum(bool(q["relevant"]) for q in queries),
                          "negatives": sum(not q["relevant"] for q in queries), "clauses": 45,
                          "dev": sum(split_of(q["id"]) == "dev" for q in queries),
                          "test": sum(split_of(q["id"]) == "test" for q in queries)}}
    try:
        for pdf in sorted(POLICIES_DIR.glob("*.pdf")):
            ingest_document(session, filename=pdf.name, data=pdf.read_bytes(), mime="application/pdf", is_synthetic=True)
        chunks = session.execute(select(Chunk, Policy.code).join(Policy, Chunk.policy_id == Policy.id)).all()
        ref_by_id = {str(c.id): ref_of(c, code) for c, code in chunks}
        report["dataset"]["chunks"] = len(ref_by_id)

        def evaluate(name, embedder, mode, reranker=None):
            # Metrics need full rankings in clause-ref space, so re-run search and map ids -> refs.
            rows, lat = [], []
            for q in queries:
                t0 = time.perf_counter()
                res = search(session, q["query"], embedder, k=10, mode=mode, reranker=reranker)
                lat.append((time.perf_counter() - t0) * 1000)
                ranked = [ref_by_id[h.chunk_id] for h in res.hits]
                row = {"id": q["id"], "split": split_of(q["id"]), "type": q["type"], "relevant": q["relevant"],
                       "best_similarity": res.best_similarity, "top": ranked[:3]}
                rel = set(q["relevant"])
                if rel:
                    row.update({f"P@{kk}": M.precision_at_k(ranked, rel, kk) for kk in KS})
                    row.update({f"R@{kk}": M.recall_at_k(ranked, rel, kk) for kk in KS})
                    row["rr"], row["ndcg10"] = M.reciprocal_rank(ranked, rel), M.ndcg_at_k(ranked, rel, 10)
                rows.append(row)
            entry = {
                "all": summarize(rows), "dev": summarize([r for r in rows if r["split"] == "dev"]),
                "test": summarize([r for r in rows if r["split"] == "test"]),
                "by_type": {t: summarize([r for r in rows if r["type"] == t]) for t in ("question", "scenario", "multi")},
                "latency_ms": {"p50": round(M.percentile(lat, 50), 1), "p95": round(M.percentile(lat, 95), 1)},
            }
            if mode != "fts":
                gate = tune_gate(rows)
                entry["gate"] = {**gate, **(gate_eval(rows, gate["threshold"]) if gate["threshold"] is not None else {})}
            report["configs"][name] = entry
            print(f"{name:55s} dev MRR {entry['dev']['mrr']:.3f}  test MRR {entry['test']['mrr']:.3f}  "
                  f"test R@5 {entry['test']['R@5']:.3f}  p50 {entry['latency_ms']['p50']} ms", flush=True)

        evaluate("fts-only (postgres ts_rank_cd, OR terms)", None, "fts")
        for model in args.models.split(","):
            for prefix in ([True, False] if "bge" in model else [False]):
                emb = FastEmbedEmbedder(model, 384, query_prefix=prefix)
                index_chunks(session, emb, reindex=True)
                tag = f"{model}{' +query-prefix' if prefix else ''}"
                evaluate(f"dense: {tag}", emb, "dense")
                evaluate(f"hybrid-rrf: {tag}", emb, "hybrid")
                if (prefix or "bge" not in model) and not args.no_rerank:
                    try:
                        evaluate(f"hybrid-rrf+rerank: {tag}", emb, "hybrid", FastEmbedReranker("Xenova/ms-marco-MiniLM-L-6-v2"))
                    except Exception as exc:  # noqa: BLE001
                        report["configs"][f"hybrid-rrf+rerank: {tag}"] = {"unavailable": f"{type(exc).__name__}: {exc}"[:200]}
    finally:
        session.close()
        trans.rollback()
        conn.close()

    report["caveats"] = [
        "Synthetic policies (45 clauses) and 108 hand-written queries; small n, wide uncertainty.",
        "Gate thresholds were tuned on the dev split only and evaluated on the test split.",
        "P@k uses denominator k, so queries with a single relevant clause cap P@5 at 0.2.",
        "Latency is wall-clock including network round trips to the hosted database.",
    ]
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"retrieval_{report['run_date']}_{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
