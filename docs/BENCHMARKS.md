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
