"""Duplicate-detector benchmark on synthetic labelled request pairs (no database).

    cd backend && .venv/Scripts/python ../evals/runners/duplicates.py

Sweeps the item-similarity threshold; picks it on the DEV split (by F1) and reports the TEST split.
Positives = exact_dup + near_dup. other_supplier pairs are reported as informational only.
"""
import hashlib
import json
import subprocess
import sys
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.retrieval.embedders import FastEmbedEmbedder
from app.services.duplicates import RequestView, classify_duplicates
from app.vendors.normalize import request_fingerprint

CASES = ROOT / "evals" / "datasets" / "duplicate_cases.json"
REPORTS = ROOT / "evals" / "reports"
BASE = datetime(2026, 1, 1, tzinfo=UTC)
MODEL = "sentence-transformers/all-MiniLM-L6-v2"


def split_of(cid: str) -> str:
    return "dev" if int(hashlib.sha1(cid.encode()).hexdigest(), 16) % 10 < 6 else "test"


def prf(tp: int, fp: int, fn: int) -> dict:
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f1 = 2 * p * r / (p + r) if p and r else None
    return {"precision": None if p is None else round(p, 4), "recall": None if r is None else round(r, 4),
            "f1": None if f1 is None else round(f1, 4), "tp": tp, "fp": fp, "fn": fn}


def main() -> None:
    cases = json.loads(CASES.read_text(encoding="utf-8"))
    emb = FastEmbedEmbedder(MODEL, 384)
    cache: dict[str, np.ndarray] = {}
    texts = sorted({i["description"] for c in cases for side in ("a", "b") for i in c[side]["items"]})
    for t, v in zip(texts, emb.embed_documents(texts), strict=True):
        cache[t] = np.asarray(v)

    def view(rid: str, r: dict) -> RequestView:
        items = [(i["description"], Decimal(i["quantity"])) for i in r["items"]]
        return RequestView(
            id=rid, request_no=rid, supplier_name=r["supplier_name"], currency="USD", total=Decimal(1000),
            category=None, submitted_at=BASE + timedelta(days=r["day"]),
            fingerprint=request_fingerprint(r["supplier_name"], items),
            item_vectors=[cache[i["description"]] for i in r["items"]],
        )

    views = {c["id"]: (view("A", c["a"]), view("B", c["b"])) for c in cases}

    def flagged(cid: str, threshold: float) -> str | None:
        a, b = views[cid]
        m = classify_duplicates(b, [a], sim_threshold=threshold)
        return m[0].kind if m else None

    sweep = []
    for t in [round(x * 0.05, 2) for x in range(8, 20)]:
        row = {"threshold": t}
        for split in ("dev", "test"):
            tp = fp = fn = 0
            for c in cases:
                if c["label"] is None or split_of(c["id"]) != split:
                    continue
                hit = flagged(c["id"], t) in {"exact", "similar"}
                tp += hit and c["label"] == 1
                fp += hit and c["label"] == 0
                fn += (not hit) and c["label"] == 1
            row[split] = prf(tp, fp, fn)
        sweep.append(row)
    best = max(sweep, key=lambda r: (r["dev"]["f1"] or 0, -r["threshold"]))
    thr = best["threshold"]

    per_type = {}
    for c in cases:
        k = flagged(c["id"], thr)
        d = per_type.setdefault(c["type"], {"n": 0, "flagged_exact": 0, "flagged_similar": 0,
                                            "flagged_other_supplier": 0, "info_repeat_purchase": 0,
                                            "not_flagged": 0})
        d["n"] += 1
        d["flagged_exact" if k == "exact" else "flagged_similar" if k == "similar"
          else "flagged_other_supplier" if k == "same_items_other_supplier"
          else "info_repeat_purchase" if k == "repeat_purchase" else "not_flagged"] += 1

    report = {
        "run_date": date.today().isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": MODEL, "cases": len(cases), "scored": sum(c["label"] is not None for c in cases),
        "chosen_threshold_by_dev_f1": thr, "at_chosen_threshold": {"dev": best["dev"], "test": best["test"]},
        "per_type_outcomes_at_threshold": per_type, "sweep": sweep,
        "caveats": ["Synthetic pairs with hand-written paraphrases; real descriptions will be messier.",
                    "Small n per type (12); split is by hash of case id."],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"duplicates_{report['run_date']}_{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "sweep"}, indent=2))
    print("\nthreshold  dev(P/R/F1)           test(P/R/F1)")
    for r in sweep:
        d, t = r["dev"], r["test"]
        print(f"{r['threshold']:<10} {d['precision']}/{d['recall']}/{d['f1']}   {t['precision']}/{t['recall']}/{t['f1']}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
