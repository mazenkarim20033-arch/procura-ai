"""Relevance-gate evaluation for the chosen default retrieval setup.

    cd backend && .venv/Scripts/python ../evals/runners/gate.py [--model NAME] [--mode dense|hybrid]

Threshold is tuned on the v1 DEV split only, then evaluated on (a) v1 test positives, (b) v1 test
negatives (very few) and (c) the 28 domain-adjacent negatives in retrieval_negatives_v2.json, which
were never used for tuning. Also reports AUC (threshold-free separability of positives vs negatives).
"""
import argparse
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from sqlalchemy.orm import Session

from app.db.session import get_engine
from app.retrieval.embedders import FastEmbedEmbedder
from app.retrieval.index import index_chunks
from app.retrieval.search import search
from app.services.ingest import ingest_document

DATA = ROOT / "evals" / "datasets"
POLICIES_DIR = ROOT / "data" / "synthetic" / "out" / "policies"
REPORTS = ROOT / "evals" / "reports"


def split_of(qid: str) -> str:
    return "dev" if int(hashlib.sha1(qid.encode()).hexdigest(), 16) % 10 < 6 else "test"


def auc(pos: list[float], neg: list[float]) -> float:
    """P(random positive scores higher than random negative); ties count half."""
    wins = sum((p > n) + 0.5 * (p == n) for p in pos for n in neg)
    return wins / (len(pos) * len(neg))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="sentence-transformers/all-MiniLM-L6-v2")
    ap.add_argument("--mode", default="dense")
    args = ap.parse_args()

    v1 = json.loads((DATA / "retrieval_queries.json").read_text(encoding="utf-8"))
    v2 = json.loads((DATA / "retrieval_negatives_v2.json").read_text(encoding="utf-8"))["queries"]
    emb = FastEmbedEmbedder(args.model, 384, query_prefix=True)

    conn = get_engine().connect()
    trans = conn.begin()
    session = Session(bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False)
    try:
        for pdf in sorted(POLICIES_DIR.glob("*.pdf")):
            ingest_document(session, filename=pdf.name, data=pdf.read_bytes(), mime="application/pdf")
        index_chunks(session, emb)

        def sim(q: str) -> float:
            return search(session, q, emb, k=6, mode=args.mode).best_similarity or 0.0

        scored = [{"id": q["id"], "split": split_of(q["id"]), "pos": bool(q["relevant"]), "sim": sim(q["query"]),
                   "query": q["query"]} for q in v1]
        fresh_neg = [{"query": q, "sim": sim(q)} for q in v2]
    finally:
        session.close()
        trans.rollback()
        conn.close()

    dev = [r for r in scored if r["split"] == "dev"]
    dpos, dneg = [r["sim"] for r in dev if r["pos"]], [r["sim"] for r in dev if not r["pos"]]
    best = (-1.0, None)
    for t in sorted(set(dpos + dneg)):
        score = (sum(s >= t for s in dpos) / len(dpos) + sum(s < t for s in dneg) / len(dneg)) / 2
        if score > best[0]:
            best = (score, t)
    thr = best[1]
    test_pos = [r["sim"] for r in scored if r["split"] == "test" and r["pos"]]
    test_neg = [r["sim"] for r in scored if r["split"] == "test" and not r["pos"]]
    fresh = [r["sim"] for r in fresh_neg]
    all_pos = [r["sim"] for r in scored if r["pos"]]
    all_neg = [r["sim"] for r in scored if not r["pos"]] + fresh

    sweep = []
    for t in [round(x * 0.05, 2) for x in range(4, 17)]:
        sweep.append({"threshold": t, "positives_passed": round(sum(s >= t for s in all_pos) / len(all_pos), 3),
                      "negatives_rejected": round(sum(s < t for s in all_neg) / len(all_neg), 3)})
    report = {
        "run_date": date.today().isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": args.model, "mode": args.mode,
        "tuned_on_dev": {"threshold": thr, "balanced_accuracy": round(best[0], 4),
                         "n_pos": len(dpos), "n_neg": len(dneg)},
        "at_tuned_threshold": {
            "v1_test_positives_passed": round(sum(s >= thr for s in test_pos) / len(test_pos), 4),
            "v1_test_negatives_rejected": f"{sum(s < thr for s in test_neg)}/{len(test_neg)}",
            "fresh_adjacent_negatives_rejected": round(sum(s < thr for s in fresh) / len(fresh), 4),
            "n_test_pos": len(test_pos), "n_fresh_neg": len(fresh),
        },
        "auc_all_positives_vs_all_negatives": round(auc(all_pos, all_neg), 4),
        "similarity_summary": {
            "positives_min_median_max": [round(min(all_pos), 3), round(sorted(all_pos)[len(all_pos) // 2], 3), round(max(all_pos), 3)],
            "negatives_min_median_max": [round(min(all_neg), 3), round(sorted(all_neg)[len(all_neg) // 2], 3), round(max(all_neg), 3)],
        },
        "threshold_sweep_all_queries": sweep,
        "highest_scoring_fresh_negatives": sorted(fresh_neg, key=lambda r: -r["sim"])[:5],
        "caveats": ["Synthetic corpus; 28 hand-written adjacent negatives; thresholds do not transfer to other models/corpora."],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"gate_{report['run_date']}_{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "threshold_sweep_all_queries"}, indent=2))
    print("\nsweep (all queries):")
    for row in sweep:
        print(row)
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
