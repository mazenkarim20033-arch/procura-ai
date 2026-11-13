"""Compliance benchmark on 40 frozen scenarios (no database).

    cd backend && .venv/Scripts/python ../evals/runners/compliance.py [--modes none,mock,groq]

Modes: `none` = deterministic rules only (the metrics that matter for the gold labels); `mock` = full
pipeline with the keyword MOCK provider (invariant checks only, NOT AI quality); `groq` = full pipeline with
the real provider configured in .env (needs LLM_PROVIDER=groq, LLM_API_KEY, LLM_MODEL).

Gold labels cover the deterministic rules only. Rules were written by the same author as the scenarios, so
rule metrics are in-distribution. Unsupported-claim and injection-susceptibility numbers are only
meaningful for a real provider.
"""
import argparse
import json
import statistics
import subprocess
import sys
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "evals"))
sys.path.insert(0, str(ROOT / "backend"))

import metrics as M
from synthetic_corpus import load_clauses

from app.ai.pipeline.context import AssessmentContext, ContractCtx, QuoteCtx
from app.ai.pipeline.core import assess
from app.ai.pipeline.corpus import MemoryPolicyCorpus
from app.ai.providers.factory import build_provider
from app.ai.providers.mock import MockProvider
from app.config import get_settings
from app.retrieval.embedders import FastEmbedEmbedder
from app.rules.intake import ItemSnapshot, QuoteSnapshot, RequestSnapshot, check_request

SCENARIOS = ROOT / "evals" / "datasets" / "compliance_scenarios.json"
REPORTS = ROOT / "evals" / "reports"
CATS = ["confirmed_violation", "potential_violation", "missing_information", "inconclusive"]
D = Decimal


def dec(v):
    return None if v in (None, "") else D(str(v))


def dt(v):
    return date.fromisoformat(v) if v else None


def build_ctx(s: dict) -> AssessmentContext:
    r = s["request"]
    items = [ItemSnapshot(i["description"], dec(i["quantity"]), dec(i["unit_cost"]),
                          dec(i["quantity"]) * dec(i["unit_cost"])) for i in r["items"]]
    snap = RequestSnapshot(r["request_no"], r["requester_name"], r["department"], r["currency"], r["supplier_name"],
                           r["justification"], dec(r["total_amount"]), dt(r["submitted_on"]), items)
    quotes = [QuoteCtx(f"q{n}", q["filename"], q["vendor"], q["currency"], dec(q["total"]), dt(q["issue_date"]),
                       dt(q["valid_until"]), q["payment_terms"], q["issue_codes"]) for n, q in enumerate(s["quotes"])]
    qsnaps = [QuoteSnapshot(q.document_id, q.filename, q.vendor_name, q.currency, q.total, q.issue_date, q.valid_until)
              for q in quotes]
    intake = {"issues": [i.as_dict() for i in check_request(snap, qsnaps)],
              "splits": s["intake_extra"].get("splits", []), "duplicates": s["intake_extra"].get("duplicates", [])}
    contracts = [ContractCtx(f"k{n}", c["filename"], c["vendor"], c["currency"], dec(c["total_value"]), c["payment_terms"])
                 for n, c in enumerate(s["contracts"])]
    return AssessmentContext(snap, quotes, contracts, s["approved_suppliers"], intake,
                             [tuple(t) for t in s["untrusted_text"]])


def prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else None
    r = tp / (tp + fn) if tp + fn else None
    f = 2 * p * r / (p + r) if p and r else None
    rnd = lambda x: None if x is None else round(x, 4)
    return {"precision": rnd(p), "recall": rnd(r), "f1": rnd(f), "tp": tp, "fp": fp, "fn": fn}


def run_mode(name, provider, scenarios, corpus, min_sim) -> dict:
    tp, fp, fn = Counter(), Counter(), Counter()
    exact = status_ok = llm_status_changes = 0
    false_approval = gold_confirmed_n = false_clean = gold_bad_n = 0
    lats, tokens_in, tokens_out = [], [], []
    llm_accepted = llm_rejected = invariant_violations = 0
    call_errors = call_retries = n_calls = 0
    rejected_reasons: Counter = Counter()
    llm_detail: list[dict] = []
    failures = []
    for s in scenarios:
        res = assess(build_ctx(s), corpus, provider, min_similarity=min_sim)
        gold = {tuple(x) for x in s["expected"]["findings"]}
        pred = {(f.rule_code, f.category) for f in res.findings if f.source == "rule" and f.category in CATS}
        for code, cat in pred | gold:
            key = (code, cat)
            bucket = tp if key in pred and key in gold else fp if key in pred else fn
            bucket[cat] += 1
        exact += pred == gold
        status_ok += res.compliance_status == s["expected"]["status"]
        if provider is not None and pred == gold and res.compliance_status != s["expected"]["status"]:
            llm_status_changes += 1  # rules agree with gold; the LLM stage legitimately moved the status
        if pred != gold or (provider is None and res.compliance_status != s["expected"]["status"]):
            failures.append({"id": s["id"], "gold": sorted(gold), "pred": sorted(pred),
                             "status_gold": s["expected"]["status"], "status_pred": res.compliance_status})
        if any(c == "confirmed_violation" for _, c in gold):
            gold_confirmed_n += 1
            false_approval += res.compliance_status == "no_issues_found"
        if gold:
            gold_bad_n += 1
            false_clean += res.compliance_status == "no_issues_found"
        for f in res.findings:  # invariants
            if (f.category == "confirmed_violation" and f.source != "rule") or (f.category != "inconclusive" and not f.evidence) \
                    or "approv" in res.compliance_status:
                invariant_violations += 1
        n_llm = sum(f.source == "llm" for f in res.findings)
        llm_accepted += n_llm
        llm_rejected += len(res.llm_rejected)
        for c in res.llm_calls:
            n_calls += 1
            call_errors += c["status"] != "ok"
            call_retries += c.get("retries") or 0
        rejected_reasons.update(r.reason for r in res.llm_rejected)
        if provider is not None and s["category"] == "adversarial":
            llm_detail.append({
                "id": s["id"], "llm_findings": [(f.rule_code, f.category, f.title) for f in res.findings if f.source == "llm"],
                "rejected": [(r.reason, r.finding.title) for r in res.llm_rejected],
                "guard_flagged": any(f.rule_code == "GUARD-INJECTION" for f in res.findings),
                "status": res.compliance_status})
        lats.append(res.latency_ms)
        if res.input_tokens is not None:
            tokens_in.append(res.input_tokens)
            tokens_out.append(res.output_tokens or 0)
    n = len(scenarios)
    per_cat = {c: prf(tp[c], fp[c], fn[c]) for c in CATS}
    micro = prf(sum(tp.values()), sum(fp.values()), sum(fn.values()))
    return {
        "mode": name, "scenarios": n,
        "per_category": per_cat, "micro": micro,
        "macro_f1": round(statistics.mean(v["f1"] for v in per_cat.values() if v["f1"] is not None), 4),
        "exact_finding_set_match": round(exact / n, 4),
        # Gold statuses describe the rules only, so they are scored only when no LLM stage runs.
        "status_accuracy": round(status_ok / n, 4) if provider is None else None,
        "status_changed_by_llm_findings": llm_status_changes if provider is not None else None,
        "false_approval_rate": {"value": round(false_approval / gold_confirmed_n, 4) if gold_confirmed_n else None,
                                "count": f"{false_approval}/{gold_confirmed_n}",
                                "definition": "gold confirmed violation but status = no_issues_found"},
        "false_clean_rate_any_issue": f"{false_clean}/{gold_bad_n}",
        "invariant_violations": invariant_violations,
        "llm": {"accepted_findings": llm_accepted, "rejected_claims": llm_rejected,
                "unsupported_claim_rate_before_verifier": round(llm_rejected / (llm_accepted + llm_rejected), 4)
                if llm_accepted + llm_rejected else None,
                "tokens_in_total": sum(tokens_in) or None, "tokens_out_total": sum(tokens_out) or None,
                "calls": n_calls, "call_errors": call_errors, "format_or_http_retries": call_retries,
                "rejected_by_reason": dict(rejected_reasons),
                "provider": provider.name if provider else None, "model": provider.model if provider else None,
                "adversarial_detail": llm_detail},
        "latency_ms": {"p50": M.percentile(lats, 50), "p95": M.percentile(lats, 95)},
        "failures": failures,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--modes", default="none,mock")
    ap.add_argument("--tag", default="", help="suffix for the report file name")
    args = ap.parse_args()
    scenarios = json.loads(SCENARIOS.read_text(encoding="utf-8"))
    settings = get_settings()
    embedder = FastEmbedEmbedder(settings.embedding_model, settings.embedding_dim, settings.embedding_query_prefix)
    corpus = MemoryPolicyCorpus(load_clauses(), embedder)
    modes = {}
    for m in args.modes.split(","):
        provider = None if m == "none" else MockProvider() if m == "mock" else build_provider(settings)
        modes[m] = run_mode(m, provider, scenarios, corpus, settings.relevance_min_similarity)
        r = modes[m]
        print(f"[{m}] micro P/R/F1 {r['micro']['precision']}/{r['micro']['recall']}/{r['micro']['f1']}  "
              f"exact {r['exact_finding_set_match']}  status {r['status_accuracy']} (llm-changed: {r['status_changed_by_llm_findings']})  "
              f"false-approval {r['false_approval_rate']['count']}  invariant violations {r['invariant_violations']}",
              flush=True)
    report = {
        "run_date": date.today().isoformat(),
        "git_sha": subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, text=True).strip(),
        "dataset": {"scenarios": len(scenarios), "by_category": dict(Counter(s["category"] for s in scenarios))},
        "embedding_model": settings.embedding_model, "relevance_threshold": settings.relevance_min_similarity,
        "modes": modes,
        "caveats": ["Gold labels cover deterministic rules only; rules and scenarios share an author (in-distribution).",
                    "Mock mode checks invariants and plumbing, not AI quality.",
                    "Unsupported-claim and injection-susceptibility figures are meaningful only for a real provider."],
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / f"compliance_{report['run_date']}_{report['git_sha']}{'_' + args.tag if args.tag else ''}.json"
    out.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    for r in modes.values():
        for f in r["failures"][:12]:
            print("FAIL", r["mode"], f)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
