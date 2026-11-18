# Benchmarks (measured results only)

Every number below comes from a report file in `evals/reports/` produced by a runner in `evals/runners/`. All data is **synthetic** (fictional company, 6 policies / 45 clauses, 68 documents), so results show how the system behaves on this corpus, not how it would perform on real procurement documents. Sample sizes are small; differences of a few hundredths are within noise.

**Reproduced on 2026-11-18 at commit `1027a68`.** The extraction, duplicate, vendor-matching, item-alignment, relevance-gate and compliance (rules and mock) runners were re-run on the current code after the project was restored from GitHub. Compared with the reports cited below, every metric was identical (the only differences were timings). The re-runs are saved as `*_2026-11-18_1027a68.json` in `evals/reports/`. The full retrieval ablation (`retrieval_2026-11-13_498ec60.json`) was **not** re-run; the retrieval code is unchanged since it was written and the gate re-run, which uses the same embedding model, reproduced exactly.

## Extraction, classification, chunking
Report: `extraction_2026-11-14_58bcc8d.json` (`evals/runners/extraction.py`; the earlier `extraction_2026-11-13_c24b531.json` predates the vendor-profile fields, all results unchanged).

| Metric | Result |
|---|---|
| Document classification accuracy | 1.00 (68 documents) |
| Field exact-match accuracy | 1.00 on every field, including vendor tax ID, address, email, phone and country (absent fields correctly read as missing) |
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
Report: `compliance_2026-11-18_1027a68.json` (`evals/runners/compliance.py --modes none,mock`; earlier runs of the same modes, `compliance_2026-11-14_91541e3.json` and `compliance_2026-11-14_0ea45c2.json`, gave the same results). 40 hand-designed scenarios (10 compliant, 10 clear violations, 8 missing-information, 6 ambiguous, 6 adversarial) with gold `(rule, category)` labels written from the policy text and frozen before the pipeline was run on them (`evals/datasets/make_compliance_scenarios.py`). Gold labels cover the **deterministic rules only**.

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
- v1 made models flag almost every laptop request with speculative "potential violations" (undocumented IT review, "requester may be self-approving", approval status unknown). v2 tells the model to report only clauses triggered by stated facts and to use `inconclusive` for requirements the data cannot verify; speculative flags dropped from 29 to 1 (120b, first run; 2 to 4 in three later repeats, see below) and 19 to 0 (20b, single run). This is a prompt change judged on the same 40 scenarios I wrote it against, so some overfitting is possible; "clean scenarios flagged" rests on 11 cases.
- The deterministic rules were never changed by the LLM stage in any run (0 false approvals, rule P/R stayed 1.00). The LLM stage can only add findings, and v2 adds mostly `inconclusive` ones, which still turn an otherwise clean request's status from `no_issues_found` to `inconclusive` (4 scenarios).
- Injection: in every injected scenario that reached the model (x01, x02, x06; x03's injected text sits in a document the model is not shown) no run followed the injected instruction; the guard flagged all four injected scenarios. Only 3 cases per run, so this is weak evidence.
- Verifier: the one model that invented numbers (20b, v1: 3 of 49 claims, 6.1%, matching `unsupported_claim_rate_before_verifier` 0.0612 in the report) was caught by the verifier; v2 had none. The "unsupported-claim rate before the verifier" is therefore 0-6% here, on a small sample. (An earlier version of this document said "3 of 41, 7.3%"; the report file says 3 of 49, and the report is right.)
- Reliability: Groq's JSON mode produced valid schema output on every call that returned; there were no format retries. The free tier rate-limits sustained load, which the provider now absorbs with Retry-After backoff; one 20b call still failed after all retries. Latency (median 4-12 s, slowest 10-16 s) is dominated by those waits and is not representative of a paid tier.
- Cost: not computed. Groq prices are not configured; `LLM_PRICE_IN_PER_M` / `LLM_PRICE_OUT_PER_M` turn the recorded token counts into an estimate.
- Default: prompt v2 and `openai/gpt-oss-120b` (0 failed calls, 0 rejected claims, no speculative flags in v2). The two models are close and single runs are noisy, so this is a weak preference, not a measured win. Run-to-run variation: repeating 120b v1 gave 40 vs 41 findings.

## How certain are the safety numbers?
Report: `safety_intervals_2026-11-18_96c0aa7.json`, produced by `evals/safety_intervals.py` from the compliance reports (Wilson 95% intervals; the script lists every report, including the labelled failed runs).

| Count (identical in every configuration, rules-only, mock and all Groq runs) | Observed | 95% interval for the true rate |
|---|---|---|
| False approvals: gold confirmed violation reported as `no_issues_found` | 0 / 12 | 0% to 24.3% |
| Any gold issue reported as `no_issues_found` | 0 / 29 | 0% to 11.7% |

"Zero in this test" is not "zero in general". With 12 and 29 cases, these data cannot rule out a true rate of up to about a quarter and about a ninth respectively. The rules are deterministic and the LLM stage can only add findings (enforced by tests and a database constraint), which is a stronger argument than the sample, but the sample alone is not strong evidence. The unsupported-claim figures quoted above (for example 3 of 49 for 20b with prompt v1) are single runs on 40 scenarios and are not given an interval here.

### Repeated runs of the default configuration (`openai/gpt-oss-120b`, prompt v2)
Reports: `compliance_2026-11-18_96c0aa7_gptoss120b_prompt-v2_repeat{1,2,3}.json`. Same 40 scenarios, same settings, three consecutive runs on 2026-11-18 (Groq free tier, temperature 0).

| | Run 1 | Run 2 | Run 3 |
|---|---|---|---|
| Rule findings P / R | 1.00 / 1.00 | 1.00 / 1.00 | 1.00 / 1.00 |
| False approvals / invariant violations | 0 / 0 | 0 / 0 | 0 / 0 |
| LLM `potential_violation` findings | 4 | 3 | 2 |
| LLM `inconclusive` findings | 36 | 37 | 36 |
| Findings accepted by the evidence verifier / claims rejected | 40 / 0 | 40 / 0 | 38 / 0 |
| Clean scenarios (11) given a model-raised potential violation | 0 | 0 | 0 |
| Clean scenarios given any LLM finding (all `inconclusive`) | 4 | 4 | 4 |
| Scenarios whose status the LLM stage changed | 4 | 4 | 4 |
| Failed calls / retries absorbed | 0 / 42 | 0 / 44 | 0 / 45 |
| Tokens per assessment (in / out) | 1,596 / 570 | 1,667 / 575 | 1,872 / 543 |
| Latency p50 / p95 (seconds, rate-limit waits included) | 11.8 / 17.8 | 11.4 / 17.1 | 9.2 / 17.1 |

What the repeats show:
- **The safety properties were stable.** Rule precision and recall, zero false approvals, zero invariant violations and zero failed calls held in all three runs, and the number of scenarios whose status moved was 4 each time. These properties come from the deterministic rules and the architecture, so stability is expected.
- **The model's own findings are not stable.** Even at temperature 0, `potential_violation` counts were 4, 3 and 2 and `inconclusive` counts 36, 37 and 36. The single earlier run reported above (1 potential violation, 39 inconclusive) falls outside this range, so "v2 cut speculative flags to 1" overstated it: across four runs the figure is **1 to 4**. The 29 of prompt v1 is still far higher, but the size of the improvement should be read as roughly 29 down to 1-4, from single runs.
- **Token use varied by about 17% in input tokens** (1,596 to 1,872 per assessment) between identical runs. A cost estimate would therefore need a range, and none is given because no prices are configured.
- Three runs is still a very small sample. No significance claims are made.

## Vendor intelligence
All data is synthetic: 9 fictional vendors (`data/synthetic/out/vendor_truth.json`), some deliberately missing a tax ID, email, phone or address, and one deliberate tax-ID conflict (the second Orion quotation prints a transposed tax ID). Everything is derived from uploaded documents; no external verification, market prices or exchange rates exist in the system.

**Vendor-name matching** (`vendor_matching_2026-11-14_cf5e691.json`, `evals/runners/vendor_matching.py`): 105 labelled pairs (63 same-vendor variants: case, legal suffix, punctuation, dropped suffix, one-letter typos; 48 different vendors, including 12 near-miss names such as "Nile Cloud Services" vs "Nile Cloud Solutions"). Pairs were frozen before tuning. Fuzzy threshold chosen on the dev split (0.92).

| Setting (test split, 47 pairs) | Precision | Recall |
|---|---|---|
| Names only | 1.00 | 0.96 (1 missed one-letter transposition) |
| Names + tax IDs (different tax IDs never merge) | 1.00 | 1.00 |

On the dev split names-only produced one false merge (a near-miss name). Fuzzy matches are therefore always marked `needs_review`, and only a human admin can merge two vendor records. Names that match exactly after normalisation but carry different tax IDs are kept as one vendor with a recorded conflict rather than silently split or merged.

**Item alignment threshold** (`item_alignment_2026-11-14_cf5e691.json`, `evals/runners/item_alignment.py`): 224 pairs (42 catalogue-item vs hand-written paraphrase, 182 different-item negatives) with real MiniLM embeddings. Dev F1 is 1.00 for cosine thresholds 0.50 to 0.70. My first guess of 0.75 would have cost recall (0.92 dev), so I measured instead: alignment uses 0.60, and price-history matching uses 0.70 (the strict end of the plateau). Paraphrases are mine, so real quotation wording will be harder.

**Not benchmarked:** price-outlier, suspiciously-low, price-gap and vendor-history flags (25%, 40% below median, 30% heuristics, not policy values) are covered by unit tests and by one live test on the synthetic deals (every injected arithmetic flaw is flagged, nothing is flagged as an outlier). With only 9 vendors and randomly generated prices there is no ground truth for "overpriced".

## Not yet measured (planned in docs/EVALUATION.md)
- **Repeated LLM runs for the other configurations.** Only the default (120b, prompt v2) was repeated three times; the 20b model and prompt v1 are single runs.
- **End-to-end latency and cost.** Latency is only recorded inside the compliance runs (dominated by free-tier rate limits) and no prices are configured, so no cost-per-assessment figure exists.
- **Scanned documents and OCR**, real (non-synthetic) documents, and Arabic: none are tested.
- **Human agreement.** There are no real reviewers; the analytics page measures AI-versus-human agreement only on the few synthetic decisions seeded for the demo.
