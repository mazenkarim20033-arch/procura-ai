"""Extraction / classification / validation / chunking benchmark on the synthetic dataset.

    cd backend && .venv/Scripts/python ../evals/runners/extraction.py

Pure functions only (no database, no LLM). Writes evals/reports/extraction_<date>_<sha>.json.
IMPORTANT: the dataset is synthetic and produced by templates the extractor was written against,
so these numbers measure in-distribution performance, not real-world accuracy.
"""
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.documents import chunk as chunking
from app.documents.classify import classify
from app.documents.extract import EXTRACTORS
from app.documents.parse import parse_bytes
from app.documents.validate import validate_extraction
from app.schemas.documents import SCHEMA_BY_TYPE

DATA = ROOT / "data" / "synthetic" / "out"
REPORTS = ROOT / "evals" / "reports"
NUMERIC = {"subtotal", "tax", "total", "total_value", "quantity", "unit_price", "line_total", "delivery_days"}


def _eq(field: str, expected, actual) -> bool:
    if expected is None or actual is None:
        return expected is None and actual is None
    if field in NUMERIC:
        try:
            return Decimal(str(expected)) == Decimal(str(actual))
        except InvalidOperation:
            return False
    return str(expected).strip().casefold() == str(actual).strip().casefold()


def _item_key(it: dict) -> tuple:
    return (it["description"].casefold(), Decimal(str(it["quantity"])), Decimal(str(it["unit_price"])),
            Decimal(str(it["line_total"])))


def _norm(s: str) -> str:
    return " ".join(s.split()).casefold()


def git_sha() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


def run() -> dict:
    truths = sorted(DATA.glob("*/*.json"))
    truths = [t for t in truths if t.name != "manifest.json"]
    cls_correct, confusion = 0, Counter()
    field_hits: dict[str, list[bool]] = defaultdict(list)
    item_tp = item_fp = item_fn = 0
    pair_tp = pair_fp = pair_fn = 0
    doc_issue_exact: list[bool] = []
    clauses_total = clauses_found = chunks_total = 0
    per_type = Counter()
    failures: list[dict] = []

    for tpath in truths:
        truth = json.loads(tpath.read_text(encoding="utf-8"))
        data = (DATA / truth["file"]).read_bytes()
        parsed = parse_bytes(data, truth["file"], "application/pdf")
        cls = classify(parsed.text)
        per_type[truth["doc_type"]] += 1
        confusion[(truth["doc_type"], cls.doc_type)] += 1
        cls_correct += cls.doc_type == truth["doc_type"]

        if truth["doc_type"] in EXTRACTORS and cls.doc_type == truth["doc_type"]:
            ex = EXTRACTORS[truth["doc_type"]](parsed)
            for fname, expected in truth["fields"].items():
                if fname == "items":
                    exp = Counter(_item_key(i) for i in expected)
                    act = Counter(_item_key(i) for i in ex.raw.get("items", []))
                    tp = sum((exp & act).values())
                    item_tp, item_fp, item_fn = item_tp + tp, item_fp + sum(act.values()) - tp, item_fn + sum(exp.values()) - tp
                    continue
                ok = _eq(fname, expected, ex.raw.get(fname))
                field_hits[f"{truth['doc_type']}.{fname}"].append(ok)
                if not ok:
                    failures.append({"file": truth["file"], "field": fname, "expected": expected,
                                     "actual": ex.raw.get(fname)})
            _, issues = validate_extraction(SCHEMA_BY_TYPE[truth["doc_type"]], ex.raw)
            got = {i.code for i in issues}
            want = set(truth["injected_issues"])
            doc_issue_exact.append(got == want)
            pair_tp += len(got & want)
            pair_fp += len(got - want)
            pair_fn += len(want - got)
            if got != want:
                failures.append({"file": truth["file"], "field": "validation_issues", "expected": sorted(want),
                                 "actual": sorted(got)})

        if truth["doc_type"] == "policy":
            drafts = chunking.chunk_policy(parsed, truth["fields"]["code"])
            chunk_texts = {_norm(d.text) for d in drafts}
            clauses_total += len(truth["clauses"])
            clauses_found += sum(_norm(c["text"]) in chunk_texts for c in truth["clauses"])
            chunks_total += len(drafts)

    def rate(n, d):
        return round(n / d, 4) if d else None

    prec, rec = rate(item_tp, item_tp + item_fp), rate(item_tp, item_tp + item_fn)
    vp, vr = rate(pair_tp, pair_tp + pair_fp), rate(pair_tp, pair_tp + pair_fn)
    f1 = lambda p, r: round(2 * p * r / (p + r), 4) if p and r else None
    return {
        "run_date": date.today().isoformat(), "git_sha": git_sha(),
        "dataset": {"documents": len(truths), "by_type": dict(per_type), "synthetic": True, "template_matched": True},
        "classification": {
            "accuracy": rate(cls_correct, len(truths)),
            "confusion": {f"{a}->{b}": n for (a, b), n in sorted(confusion.items()) if a != b},
        },
        "field_exact_match": {k: {"accuracy": rate(sum(v), len(v)), "n": len(v)} for k, v in sorted(field_hits.items())},
        "line_items": {"precision": prec, "recall": rec, "f1": f1(prec, rec), "tp": item_tp, "fp": item_fp, "fn": item_fn},
        "validation": {
            "docs_with_exact_issue_set": rate(sum(doc_issue_exact), len(doc_issue_exact)),
            "issue_precision": vp, "issue_recall": vr, "f1": f1(vp, vr),
        },
        "policy_chunking": {"clauses": clauses_total, "clause_recall": rate(clauses_found, clauses_total),
                            "chunks": chunks_total},
        "failures": failures[:50],
        "caveats": [
            "Synthetic data generated from the same templates the rule-based extractor targets: in-distribution only.",
            "No scanned/OCR documents are in this set; OCR is unverified.",
            "Field confidence scores are not produced by rule-based extraction.",
        ],
    }


if __name__ == "__main__":
    report = run()
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"extraction_{report['run_date']}_{report['git_sha']}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "failures"}, indent=2, default=str))
    print(f"\nfailures recorded: {len(report['failures'])}\nwrote {out}")
