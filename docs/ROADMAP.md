# Implementation Roadmap

Each milestone ends with: tests run, functionality verified, weaknesses noted, docs updated, status report, Git commit. **Nothing is pushed without your approval.**

| # | Milestone | Key deliverables | Exit criteria |
|---|---|---|---|
| 1 | Environment & repo | Private repo, README, planning docs | Done (this commit pending approval) |
| 2 | Requirements & architecture | PRD, architecture, eval strategy, costs/risks | **You approve this plan** |
| 3 | DB + backend foundation | Supabase Postgres+pgvector connection (no Docker), SQLAlchemy models, Alembic migration, config, logging, health endpoints, error handling, audit log with hash chain, auth stub | Migrations apply cleanly; health/ready green; unit+integration tests pass |
| 4 | Document ingestion | Upload, parse, OCR (if installed), classify, extract w/ provenance, validators, chunker; synthetic data generator v1 (policies + quotes) | Extraction accuracy measured on templated set; OCR test on scanned sample; tests pass  Status: done except OCR (unverified) and LLM fallback. |
| 5 | RAG engine | Embedder/VectorStore/Reranker interfaces, hybrid search, relevance gate, retrieval eval runner | Retrieval metrics produced from a real run; ablation table  Status: done; see docs/BENCHMARKS.md. |
| 6 | Purchase request intelligence | Request model/API, missing/inconsistent checks, duplicate/split detection | Rule tests + synthetic dup cases pass  Status: done; see docs/BENCHMARKS.md. |
| 7 | Compliance engine | Rules engine, LLM provider abstraction (Anthropic/OpenAI-compat/Mock), prompts@v1, pipeline, evidence verifier, injection guard | Golden cases run; false-approval-rate and unsupported-claim rate measured; invariant "AI can't approve" tested  Status: done; benchmarked with mock and real Groq models (prompt v1 vs v2), see docs/BENCHMARKS.md. |
| 8 | Vendor intelligence | Normalization, quote comparison, price anomalies | Tests with alias/fuzzy cases  Status: done; see docs/BENCHMARKS.md. |
| 9 | Human approval workflow | Decisions, finding reviews, info requests, history | State-machine tests; approve only via decision  Status: done (rules unit-tested, workflow tested against the live database). |
| 10 | Analytics & audit | Aggregations, audit viewer, chain verification | Numbers match DB; chain verify test  Status: done (live-DB tested). |
| 11 | Frontend | All 9 pages wired to API, dark design system, responsive | Every control functional; manual + Playwright smoke tests; screenshots |
| 12 | Evaluation & benchmarking | Full dataset, runners, reports, ablations, N=3 LLM runs | Reports in `evals/reports`; BENCHMARKS.md generated |
| 13 | Hardening & deployment | CI, load/latency pass, free-tier deployment attempt, demo mode polish | Fresh-clone setup works in ≤5 commands; deployed demo or documented blockers |
| 14 | Portfolio case study | Architecture diagram, results, screenshots, demo video script, limitations, future work | Page uses only measured numbers |

## Suggested ordering for impact
M3 → M4 → M5 → M7 (core intelligence) before M11 (UI), so the UI is built over real behaviour. A thin vertical slice (one request end-to-end in mock mode) is targeted at the end of M7.
