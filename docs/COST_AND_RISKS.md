# Cost Analysis & Risk Register

## 1. Cost: what runs entirely free

| Component | Free option | Notes |
|---|---|---|
| Postgres + pgvector | Neon free tier (dev and deployment); Supabase as alternative | Storage/compute caps (~0.5 GB on Neon free), scale-to-zero cold starts, requires internet. Docker dropped because the dev PC can't run it |
| Embeddings | `bge-small-en-v1.5` local CPU | ~130 MB model download; fine on CPU for demo corpus |
| Reranker | MiniLM cross-encoder local | Optional; adds latency |
| PDF parsing, chunking, rules, analytics | PyMuPDF etc. | |
| OCR | Tesseract (separate Windows install) | Optional |
| LLM (real) | **Ollama local model** (e.g., Qwen/Llama class) or provider free credits | Quality of structured output with small local models must be measured; may be weaker |
| LLM (paid, optional) | Anthropic / OpenAI API | Pay per token; I will record tokens and compute cost per assessment from the real usage — I won't quote a figure until measured |
| Demo mode | Mock provider | Free, no keys |
| Frontend hosting | Vercel/Netlify free | |
| API hosting | Render/Fly free tiers | Cold starts; RAM limits may block the embedding model |
| CI | GitHub Actions (free for private repos within quota) | |

**Bottom line:** the full app including real retrieval, rules, extraction, analytics and demo mode costs $0 to run locally. Only "real LLM reasoning" needs either a local model (free, slower/weaker) or a paid API (small per-assessment cost, measured later).

## 2. Risks and mitigations

| # | Risk | Likelihood / impact | Mitigation |
|---|---|---|---|
| 1 | LLM hallucinates policy references | High / Critical | Evidence verifier (substring + chunk-id membership), schema-forced citations, rules own confirmed violations, relevance gate → `inconclusive` |
| 2 | False approval (missed violation) | Med / Critical | AI cannot approve; deterministic rules for hard constraints; false-approval-rate tracked as headline metric; reviewer always decides |
| 3 | Prompt injection via uploaded docs | Med / High | Section 6.5 of ARCHITECTURE; adversarial eval cases; no tool access for LLM |
| 4 | Synthetic data makes metrics look better than reality | High / High (credibility) | Adversarial/messy cases, held-out split, explicit limitation text, never claim real-world accuracy |
| 5 | Extraction fails on messy/scanned PDFs | High / Med | OCR fallback, confidence per field, validation errors surfaced as `MISSING_INFORMATION`, never silently guessed |
| 6 | Scope too large for quality | High / High | Milestones with exit criteria; each ends working and tested; defer Arabic content, reranker, deployment polish if needed |
| 7 | Small local LLMs produce invalid JSON | Med / Med | Validation + retry-with-feedback; measure failure rate; mock/Anthropic as reference |
| 8 | Embedding model memory on free hosting | Med / Med | Precompute demo embeddings; or HF inference; decide at M13 |
| 9 | Windows environment friction (Docker, Tesseract, paths) | Med / Low | Docker Desktop installed (daemon status to confirm); Tesseract optional with skipped tests |
| 10 | Non-determinism makes tests flaky | Med / Med | temp 0, mock provider in unit/integration tests, tolerance bands in eval |
| 11 | Mock mode mistaken for real AI | Med / High | Persistent UI badge, `is_mock` on assessment rows, README disclosure |
| 12 | Confidence scores misleading | Med / Med | Label as uncalibrated heuristic; calibration plot only if measured |
| 13 | Audit log tampering claims overstated | Low / Med | Hash chain + insert-only trigger documented as tamper-*evident*, not tamper-proof |
