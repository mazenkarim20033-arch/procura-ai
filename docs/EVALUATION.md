# Evaluation & Benchmarking Strategy

**Rule:** no number appears in README, case study, or UI unless produced by `evals/` runners and stored under `evals/reports/` with git SHA, config, and date. All datasets are synthetic and labelled so; results do not generalize to real procurement data and the write-up will say so.

## 1. Dataset (seeded generator + hand-curated edge cases)
`data/synthetic/generate.py` (fixed seed) produces PDFs and JSON ground truth.

| Asset | Target size v1 |
|---|---|
| Policy documents (spend thresholds, quote rules, approved vendors, category rules, travel/IT/services, conflict-of-interest, contract rules) | 6 policies, ~120 clauses, incl. superseded versions and one deliberately ambiguous/contradictory clause pair |
| Purchase requests | 80: ~25 compliant, ~20 clear violations (each tagged with violated clause ids), ~15 missing info, ~12 ambiguous (human review needed), ~8 adversarial (prompt injection in attachments, split purchases, mismatched totals) |
| Vendor quotations | ~150 (1–4 per request), varied layouts (3 templates + messy), some scanned/rotated for OCR |
| Contracts / invoices | ~20 / ~30 with known field values |
| Retrieval queries | ~150 (query → set of relevant clause ids), written by me by hand-labelling from ground-truth generator links, then spot-audited |
| Arabic | 1 small policy + 5 queries, reported separately and only if included (open question) |

Each case stores `expected_findings[]` (category, rule/clause id), `expected_fields{}`, `expected_status`.

## 2. Metrics

**Retrieval** (`evals/runners/retrieval.py`): Precision@k, Recall@k (k=1,3,5,10), MRR, nDCG@10; ablations: dense-only vs FTS-only vs hybrid vs hybrid+rerank, chunking strategies, embedding models. Context relevance: fraction of top-k judged relevant by gold labels (and, separately, by an LLM judge reported as such).

**Extraction**: per-field exact/normalized match, numeric tolerance for amounts, line-item F1, document-classification accuracy and confusion matrix; rules-only vs LLM-fallback vs mock.

**Compliance classification**: per-class precision/recall/F1 over the 5 categories, matched on (category, rule/clause id). Macro-F1.
- **False approval rate** = (cases with ≥1 gold `CONFIRMED_VIOLATION` where the assessment reports `no_issues_found`) / (cases with gold violations). Headline safety metric; target 0 on the gold set, reported with count and CI (small n — Wilson interval).
- **Unsupported-claim rate** = findings whose evidence fails verification or doesn't support the claim on manual/LLM-judge check / total findings. Two numbers: *before* verifier (raw model behaviour) and *after* (shipped behaviour).
- **Injection robustness**: adversarial cases where the injected instruction changes the assessment; pass = no change in status/findings except the added injection flag.

**Operational**: end-to-end assessment latency (p50/p95), tokens per assessment, estimated cost per assessment (provider list price × recorded tokens; labelled estimate), stage-level latency breakdown.

## 3. Method
- LLM-dependent metrics run with a real provider at temperature 0, N=3 runs to expose variance; report mean and range. Mock runs are *not* reported as AI quality.
- Gold labels frozen before tuning; thresholds (retrieval relevance gate, injection patterns) tuned on a dev split (60%), reported on a held-out test split (40%).
- Every report includes model id, prompt versions, embedding model, commit SHA.
- CI runs a fast deterministic subset (rules, extraction on templates, retrieval with the local embedder) and fails on regression beyond tolerance; full LLM eval is run manually.

## 4. Deliverables
`evals/reports/<date>_<sha>.json` + generated `BENCHMARKS.md` table; case study pulls only from these files.
