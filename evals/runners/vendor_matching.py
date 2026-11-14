"""Vendor-name matching benchmark (no database, no model).

    cd backend && .venv/Scripts/python ../evals/runners/vendor_matching.py

A pair is predicted "same vendor" when resolve_vendor() matches b against a candidate built from a.
Two settings: names only, and names with tax IDs (near-miss negatives carry different tax IDs; positives
carry the same one when the vendor has one). The fuzzy threshold is chosen on the DEV split of the
names-only setting and reported on TEST.
"""
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.vendors.resolve import Candidate, Profile, resolve_vendor

PAIRS = ROOT / "evals" / "datasets" / "vendor_pairs.json"
REPORTS = ROOT / "evals" / "reports"


def split_of(pid: str) -> str:
    return "dev" if int(hashlib.sha1(pid.encode()).hexdigest(), 16) % 10 < 6 else "test"


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    rd = lambda x: None if x is None else round(x, 4)
    return {"precision": rd(p), "recall": rd(r), "f1": rd(f), "tp": tp, "fp": fp, "fn": fn}


def predict(pair, threshold, use_tax):
    cand = Candidate("A", pair["a"]["name"], pair["a"]["tax_id"] if use_tax else None)
    dec = resolve_vendor(Profile(pair["b"]["name"], pair["b"]["tax_id"] if use_tax else None), [cand], fuzzy_threshold=threshold)
    return dec.action == "match"


def score(pairs, threshold, use_tax):
    tp = fp = fn = 0
    for p in pairs:
        hit = predict(p, threshold, use_tax)
        tp += hit and p["label"] == 1
        fp += hit and p["label"] == 0
        fn += (not hit) and p["label"] == 1
    return prf(tp, fp, fn)


def main() -> None:
    pairs = json.loads(PAIRS.read_text(encoding="utf-8"))
    dev = [p for p in pairs if split_of(p["id"]) == "dev"]
    test = [p for p in pairs if split_of(p["id"]) == "test"]
    sweep = []
    for t in [round(x * 0.02, 2) for x in range(40, 51)]:  # 0.80 .. 1.00
        sweep.append({"threshold": t, "dev": score(dev, t, False), "test": score(test, t, False)})
    best = max(sweep, key=lambda r: (r["dev"]["f1"] or 0, r["threshold"]))
    thr = best["threshold"]
    kinds = {}
    for p in pairs:
        k = kinds.setdefault(p["kind"], {"n": 0, "predicted_same_names_only": 0, "predicted_same_with_tax_ids": 0})
        k["n"] += 1
        k["predicted_same_names_only"] += predict(p, thr, False)
        k["predicted_same_with_tax_ids"] += predict(p, thr, True)
    report = {
        "run_date": date.today().isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "pairs": len(pairs), "dev": len(dev), "test": len(test),
        "chosen_threshold_by_dev_f1_names_only": thr,
        "names_only": {"dev": score(dev, thr, False), "test": score(test, thr, False)},
        "with_tax_ids": {"dev": score(dev, thr, True), "test": score(test, thr, True)},
        "per_kind_predicted_same": kinds, "sweep_names_only": sweep,
        "caveats": ["Synthetic variants of 9 fictional vendors; near-miss negatives are my own invention.",
                    "Small n; the dev/test split is by hash of pair id."],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"vendor_matching_{report['run_date']}_{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "sweep_names_only"}, indent=2))
    print("\nthreshold  dev P/R/F1          test P/R/F1")
    for r in sweep:
        d, t = r["dev"], r["test"]
        print(f"{r['threshold']:<10} {d['precision']}/{d['recall']}/{d['f1']}   {t['precision']}/{t['recall']}/{t['f1']}")
    print(f"\nwrote {out}")


if __name__ == "__main__":
    main()
