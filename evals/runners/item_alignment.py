"""Item-description similarity benchmark: calibrates the cosine threshold used to align quotation line items
(vendor comparison) with real MiniLM embeddings. No database.

    cd backend && .venv/Scripts/python ../evals/runners/item_alignment.py

Positives: a catalogue item vs a hand-written paraphrase of it. Negatives: a catalogue item vs a paraphrase of a
DIFFERENT item (including items from the same family, e.g. laptop vs monitor). The threshold is chosen on the
DEV split (by F1; ties go to the middle of the plateau) and reported on TEST.
"""
import hashlib
import json
import subprocess
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "evals" / "datasets"))

from make_duplicate_cases import PARAPHRASES

from app.config import get_settings
from app.retrieval.embedders import FastEmbedEmbedder

REPORTS = ROOT / "evals" / "reports"


def split_of(pid: str) -> str:
    return "dev" if int(hashlib.sha1(pid.encode()).hexdigest(), 16) % 10 < 6 else "test"


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    rd = lambda x: None if x is None else round(x, 4)
    return {"precision": rd(p), "recall": rd(r), "f1": rd(f), "tp": tp, "fp": fp, "fn": fn}


def main() -> None:
    s = get_settings()
    emb = FastEmbedEmbedder(s.embedding_model, 384, True)
    items = list(PARAPHRASES)
    texts = sorted({*items, *(p for ps in PARAPHRASES.values() for p in ps)})
    vec = dict(zip(texts, (np.asarray(v) / np.linalg.norm(v) for v in emb.embed_documents(texts)), strict=True))
    pairs = []
    for a in items:
        for k, para in enumerate(PARAPHRASES[a]):
            pairs.append({"id": f"pos:{a}:{k}", "label": 1, "sim": float(vec[a] @ vec[para])})
    for i, a in enumerate(items):
        for j, b in enumerate(items):
            if a != b:
                para = PARAPHRASES[b][(i + j) % len(PARAPHRASES[b])]
                pairs.append({"id": f"neg:{a}:{b}", "label": 0, "sim": float(vec[a] @ vec[para])})
    for p in pairs:
        p["split"] = split_of(p["id"])

    def score(split, t):
        tp = fp = fn = 0
        for p in pairs:
            if p["split"] != split:
                continue
            hit = p["sim"] >= t
            tp += hit and p["label"] == 1
            fp += hit and p["label"] == 0
            fn += (not hit) and p["label"] == 1
        return prf(tp, fp, fn)

    sweep = [{"threshold": t, "dev": score("dev", t), "test": score("test", t)} for t in [round(x * 0.05, 2) for x in range(6, 20)]]
    best_f1 = max(r["dev"]["f1"] or 0 for r in sweep)
    plateau = [r["threshold"] for r in sweep if (r["dev"]["f1"] or 0) >= best_f1 - 1e-9]
    chosen = plateau[len(plateau) // 2]
    pos = sorted(p["sim"] for p in pairs if p["label"] == 1)
    neg = sorted(p["sim"] for p in pairs if p["label"] == 0)
    report = {
        "run_date": date.today().isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "model": s.embedding_model, "pairs": len(pairs),
        "positives_min_median_max": [round(pos[0], 3), round(pos[len(pos) // 2], 3), round(pos[-1], 3)],
        "negatives_min_median_max": [round(neg[0], 3), round(neg[len(neg) // 2], 3), round(neg[-1], 3)],
        "dev_f1_plateau": plateau, "chosen_threshold": chosen,
        "at_chosen": {"dev": score("dev", chosen), "test": score("test", chosen)}, "sweep": sweep,
        "caveats": ["Hand-written paraphrases of 14 invented catalogue items; real quotation wording is messier."],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"item_alignment_{report['run_date']}_{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "sweep"}, indent=2))
    for r in sweep:
        d, t = r["dev"], r["test"]
        print(f"{r['threshold']:<6} dev {d['precision']}/{d['recall']}/{d['f1']}   test {t['precision']}/{t['recall']}/{t['f1']}")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
