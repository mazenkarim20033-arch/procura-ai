# Benchmarks (measured results only)

Every number below comes from a report file in `evals/reports/` produced by a runner in `evals/runners/`. All data is **synthetic** (fictional company, 6 policies / 45 clauses, 68 documents), so results show how the system behaves on this corpus, not how it would perform on real procurement documents. Sample sizes are small; differences of a few hundredths are within noise.

## Extraction, classification, chunking
Report: `extraction_2026-11-13_c24b531.json` (`evals/runners/extraction.py`).

| Metric | Result |
|---|---|
| Document classification accuracy | 1.00 (68 documents) |
| Field exact-match accuracy | 1.00 on every field |
| Line-item precision / recall | 1.00 / 1.00 (106 items) |
| Validation issue precision / recall | 1.00 / 1.00 (injected arithmetic and date flaws) |
| Policy clause chunking recall | 1.00 (45 of 45 clauses became exactly one chunk) |

**Read this as a regression baseline, not as accuracy.** The extractor was written against the same templates the generator produces, so it is tested in-distribution. No scanned documents are included; OCR is untested. One earlier run showed 0.80 validation F1: that was a mislabelled expectation in my truth data, fixed in the data, not the extractor.

## Retrieval
Report: `retrieval_2026-11-13_498ec60.json` (`evals/runners/retrieval.py`). 108 hand-written queries (96 positive, 12 negative), frozen before tuning; split 71 dev / 37 test by hash of the query id. Metrics below are on **test positives**.

| Config | MRR | P@1 | R@3 | R@5 | R@10 | nDCG@10 |
|---|---|---|---|---|---|---|
| FTS only (Postgres, OR terms) | 0.585 | 0.49 | 0.61 | 0.67 | 0.79 | 0.62 |
| Dense bge-small + query prefix | 0.774 | 0.71 | 0.75 | 0.88 | 0.96 | 0.81 |
| Dense bge-small, no prefix | 0.753 | 0.66 | 0.81 | 0.85 | 0.96 | 0.80 |
| Hybrid RRF bge-small + prefix | 0.685 | 0.57 | 0.75 | 0.79 | 0.94 | 0.74 |
| Hybrid RRF + cross-encoder rerank (bge) | 0.765 | 0.69 | 0.81 | 0.86 | 0.93 | 0.79 |
| **Dense MiniLM-L6-v2 (default)** | **0.790** | 0.71 | 0.81 | 0.87 | 0.99 | 0.83 |
| Hybrid RRF MiniLM | 0.670 | 0.54 | 0.70 | 0.84 | 0.94 | 0.73 |
| Hybrid RRF + rerank (MiniLM) | 0.765 | 0.69 | 0.81 | 0.86 | 0.93 | 0.79 |

Findings:
- Dense retrieval beat keyword search and beat hybrid RRF. On this corpus the keyword side adds noise (queries are paraphrases, and OR-term matching favours generic words). Hybrid remains implemented and selectable.
- The cross-encoder recovered hybrid's loss but did not beat dense alone and cost latency, so it is off by default.
- The default model was chosen by **dev-split** MRR (MiniLM 0.826 vs bge-small 0.809). That gap is not statistically meaningful; MiniLM is also smaller and a little faster.
- Median wall-clock latency per query was 2.4-2.9 s for dense (CPU query embedding on a weak laptop plus a round trip to the hosted database), 0.2 s for FTS only. Not optimised.

## Relevance gate (when to say "no applicable policy found")
Report: `gate_2026-11-13_586e566.json` (`evals/runners/gate.py`). Threshold on best cosine similarity, tuned on the dev split only (0.385, MiniLM dense).

| Measure | Result |
|---|---|
| Test positives passing the gate | 35 / 35 (1.00) |
| Fresh domain-adjacent negatives rejected (28, never used for tuning) | 22 / 28 (0.79) |
| v1 test negatives rejected | 1 / 2 (too few to mean anything) |
| AUC, all positives vs all negatives | 0.94 |

So roughly one in five off-topic but procurement-flavoured questions still passes the gate (highest-scoring offenders: "How should purchase orders be numbered?", "What is the process to dispute an invoice with a supplier?"). The gate reduces, but does not eliminate, the chance of reasoning over irrelevant clauses; the evidence verifier and human review remain necessary. The threshold is specific to this model and corpus.

## Duplicate detection
Reports: `duplicates_2026-11-13_791e6af.json` (run 1) and `duplicates_2026-11-13_21e4d1a.json` (run 2) from `evals/runners/duplicates.py`. 64 synthetic request pairs (52 scored), labelled by construction and frozen before tuning (`evals/datasets/make_duplicate_cases.py`); real MiniLM embeddings; paraphrases are hand-written by me.

| Run | Precision | Recall | Notes |
|---|---|---|---|
| 1 (test split) | 0.60 | 1.00 | All 12 false positives were identical requests 120-300 days apart, flagged "exact" |
| 2 (test split) | 1.00 | 1.00 | Identical requests outside the 90-day window now report as informational `repeat_purchase` |

The run-1 failures exposed a design flaw (a legitimate repeat order is not a duplicate), not a threshold problem; I changed the logic, then re-ran. F1 is 1.0 on dev for every similarity threshold from 0.65 to 0.85, so the shipped default (0.80) sits inside that plateau rather than at its edge. Treat the perfect score with suspicion: the pairs are easy and synthetic (n = 12 per type), so this shows the logic does what it is meant to on cases I could think of, not that it will catch messy real-world duplicates. Split-purchase and near-threshold detection are covered by unit tests only; they have no benchmark.

## Compliance assessment
Report: `compliance_2026-11-14_7fabb54.json` (`evals/runners/compliance.py`). 40 hand-designed scenarios (10 compliant, 10 clear violations, 8 missing-information, 6 ambiguous, 6 adversarial) with gold `(rule, category)` labels written from the policy text and frozen before the pipeline was run on them (`evals/datasets/make_compliance_scenarios.py`). Gold labels cover the **deterministic rules only**.

| Rules only (no LLM) | Result |
|---|---|
| Precision / recall / F1 over (rule, category) pairs | 1.00 / 1.00 / 1.00 (35 expected findings) |
| Per category (confirmed 14, potential 10, missing 10, inconclusive 1) | 1.00 precision and recall each |
| Exact finding-set match / status accuracy | 40 / 40 and 40 / 40 |
| False approval rate (gold confirmed violation, status `no_issues_found`) | 0 / 12 |
| Scenarios with any gold issue reported as `no_issues_found` | 0 / 29 |
| Invariant violations (LLM-confirmed violation, finding without evidence, an "approved" status) | 0 |

Full pipeline with the **mock** provider: the same rule results (the LLM stage never hid or changed a rule finding), 0 invariant violations, 40 mock findings accepted and none rejected. The mock adds a keyword-based IT-review finding to every laptop request, so it moved the status away from the rules-only gold in 20 scenarios; status is therefore not scored in that mode. **These numbers say nothing about AI quality.**

How to read the perfect rule scores: the rules and the scenarios were written by the same person against the same policy text, so this is a consistency and regression check, not a measure of how well the rules would hold up on other people's requests. Only one scenario exercises the `inconclusive` category and 12 exercise confirmed violations, so per-category figures rest on very few cases.

### Real LLM stage (Groq), prompt v1 vs v2
Reports: `compliance_2026-11-14_6bc9bd6_gptoss{20b,120b}_prompt-v{1,2}.json` (plus earlier repeats and two instructive failed runs, kept and labelled: `*_run1_stage-gated-off`, `*_run2_rate-limited`). Same 40 scenarios, `openai/gpt-oss-20b` and `openai/gpt-oss-120b` on Groq's free tier, temperature 0, one run per configuration.

| | 120b v1 | 120b v2 | 20b v1 | 20b v2 |
|---|---|---|---|---|
| Rule findings P / R | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| False approvals / invariant violations | 0 / 0 | 0 / 0 | 0 / 0 | 0 / 0 |
| LLM `potential_violation` findings | 29 | 1 | 19 | 0 |
| LLM `inconclusive` findings | 12 | 39 | 22 | 30 |
| Clean scenarios (11) given a model-raised potential violation | 4 | 0 | 2 | 0 |
| Scenarios whose status the LLM stage changed | 11 | 4 | 9 | 4 |
| Claims rejected by the evidence verifier | 0 | 0 | 3 (invented numbers) | 0 |
| Failed calls / retries absorbed | 0 / 28 | 0 / 44 | 0 / 38 | 1 / 38 |
| Tokens per assessment (in / out) | 1,117 / 554 | 1,379 / 514 | 1,117 / 597 | 1,251 / 435 |

What this shows, and what it does not:
- v1 made models flag almost every laptop request with speculative "potential violations" (undocumented IT review, "requester may be self-approving", approval status unknown). v2 tells the model to report only clauses triggered by stated facts and to use `inconclusive` for requirements the data cannot verify; speculative flags dropped from 29 to 1 (120b) and 19 to 0 (20b). This is a prompt change judged on the same 40 scenarios I wrote it against, so some overfitting is possible; "clean scenarios flagged" rests on 11 cases.
- The deterministic rules were never changed by the LLM stage in any run (0 false approvals, rule P/R stayed 1.00). The LLM stage can only add findings, and v2 adds mostly `inconclusive` ones, which still turn an otherwise clean request's status from `no_issues_found` to `inconclusive` (4 scenarios).
- Injection: in every injected scenario that reached the model (x01, x02, x06; x03's injected text sits in a document the model is not shown) no run followed the injected instruction; the guard flagged all four injected scenarios. Only 3 cases per run, so this is weak evidence.
- Verifier: the one model that invented numbers (20b, v1: 3 of 41 claims, 7.3%) was caught by the verifier; v2 had none. The "unsupported-claim rate before the verifier" is therefore 0-7% here, on a small sample.
- Reliability: Groq's JSON mode produced valid schema output on every call that returned; there were no format retries. The free tier rate-limits sustained load, which the provider now absorbs with Retry-After backoff; one 20b call still failed after all retries. Latency (median 4-12 s, slowest 10-16 s) is dominated by those waits and is not representative of a paid tier.
- Cost: not computed. Groq prices are not configured; `LLM_PRICE_IN_PER_M` / `LLM_PRICE_OUT_PER_M` turn the recorded token counts into an estimate.
- Default: prompt v2 and `openai/gpt-oss-120b` (0 failed calls, 0 rejected claims, no speculative flags in v2). The two models are close and single runs are noisy, so this is a weak preference, not a measured win. Run-to-run variation: repeating 120b v1 gave 40 vs 41 findings.
