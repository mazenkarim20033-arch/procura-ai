# Backend

Milestone 3 (foundation) — implemented and tested:

- FastAPI app with request-id logging (JSON), problem+json errors, CORS, `/health/live`, `/health/ready` (DB + pgvector + LLM provider mode).
- SQLAlchemy models for the full planned schema (27 tables); DDL generated to `migrations/sql/0001_initial.sql`.
- DB-level integrity: append-only `audit_log`, immutable assessments/findings/decisions, "only rules can confirm violations", "a request is approved/rejected only after a matching human decision", RLS on every table.
- Hash-chained audit log service (`app/services/audit.py`), demo-grade role enforcement (`app/api/auth.py`).

Milestone 4 (document ingestion) — implemented and tested:

- `app/documents/`: PDF/TXT parsing (PyMuPDF), rule-based classification, rule-based field extraction with per-field source tracking (page, offsets, text), strict Pydantic models, arithmetic/date validation, clause-level policy chunking.
- `app/services/ingest.py`: parse → classify → extract → validate → chunk → persist (dedupe by SHA-256). Chunks are stored without embeddings; embedding arrives in milestone 5.
- API: `POST /documents` (multipart; only admins may upload policies), `GET /documents`, `GET /documents/{id}`. Uploads are audit-logged.
- Benchmark: `evals/runners/extraction.py` → `evals/reports/`. See `data/synthetic/README.md`.

Limitations: extraction is rule-based and only handles "Label: value" headers plus one-line item rows; no field-level confidence; **OCR code exists but is unverified** (Tesseract is not installed here, so scanned pages produce a warning instead of text); no DOCX/image upload; no LLM fallback yet; the `pymupdf` package currently pulls in heavy optional dependencies (onnxruntime etc.) that should be trimmed before deployment.

Milestone 5 (retrieval) — implemented and tested:

- `app/retrieval/`: `Embedder`/`Reranker` interfaces; fastembed (ONNX, no torch) embedder, a test-only hashing embedder, optional cross-encoder reranker; `index_chunks` (embeds the context-prefixed text, keeps `Chunk.text` verbatim for citations); hybrid search = pgvector cosine + Postgres FTS fused with RRF, filtered by policy status / effective date / category / code; relevance gate; retrieval logging.
- API: `GET /policies`, `GET /policies/{id}`, `POST /policies/search` (debug view of what the pipeline would retrieve), `POST /policies/reindex` (admin).
- Benchmark: `evals/runners/retrieval.py` (ablations over search mode, embedding model, query prefix, reranker). Results live in `evals/reports/`; the embedding model downloads to the fastembed cache on first use (about 130 MB for bge-small).
- Test-suite embedder is a hashing stub, so the unit/integration tests verify SQL, filters and wiring, not retrieval quality.

Milestone 6 (purchase request intelligence) — implemented and tested:

- `POST /requests` (all fields optional: incomplete requests are accepted and reported), `POST /requests/from-document/{id}` (from an extracted purchase-request PDF), `GET /requests`, `GET /requests/{id}`, `POST /requests/{id}/documents`, `GET /requests/{id}/intake`.
- `app/rules/intake.py`: deterministic checks for missing information, arithmetic/currency/date inconsistencies, and request-vs-quotation comparison (competing quotes are normal; it only warns if none matches the requested supplier).
- `app/services/duplicates.py`: exact duplicates (fingerprint), similar requests (item-embedding similarity), same-items-other-supplier, informational repeat purchases, split-purchase and near-threshold detection (USD only: no exchange-rate source, so other currencies are reported as a limitation).
- The intake report is computed live and not stored; milestone 7 folds it into the persisted assessment. Requests are never approved here; status stays `submitted`.
- Migration `0002` (applied with `alembic upgrade head`); migration SQL is now frozen/hand-written and `schema_snapshot.sql` is a drift-checked snapshot.

Limitations: no vendor identity resolution yet (names are compared after simple normalisation); category is not extracted from documents so split detection matches on supplier and period only (and says so); request-vs-quote total variance threshold (15%) and the near-threshold band (15%) are heuristics, not policy values.

Milestone 7 (compliance engine) — implemented and tested:

- `app/rules/policy_rules.py`: deterministic rules tied to specific policy clauses (quotation count and validity, quotation content/arithmetic, approved supplier, justification, split/duplicate signals, payment terms, injection guard). Each finding cites the clause it was looked up from; if a clause is not loaded the finding degrades to `inconclusive`. Only rules can emit `confirmed_violation` (also a database CHECK constraint). "Missing information" is never reported as a violation.
- `app/ai/`: provider interface with a **mock** provider (keyword heuristics, labelled `[MOCK]` and `is_mock` end to end) and an OpenAI-compatible provider for Groq (temperature 0, JSON output validated against a Pydantic schema, validation-error feedback retries, backoff on 429/5xx, token/latency tracking; tested with a mocked transport and benchmarked against the real Groq API (see docs/BENCHMARKS.md)); versioned prompts with SHA-256 recorded per call; injection scan; evidence verifier (clause must have been shown, quote must be verbatim, no unsupported numbers); LLM stage only sees clauses the rules do not own, retrieved first.
- Pipeline: rules -> retrieval + LLM -> verification -> aggregation (risk score, status, heuristic confidence, financial risks, next steps) -> persist immutable assessment + findings + evidence + retrieval/LLM logs + AI-actor audit entry. The request status moves to `assessed`, never to approved/rejected.
- API: `POST /requests/{id}/assess` (reviewer/admin), `GET /requests/{id}/assessments`, `GET /assessments/{id}`, `GET|PUT /settings/approved-suppliers` (admin to write).
- Benchmark: `evals/runners/compliance.py`; results in `docs/BENCHMARKS.md`.

To use Groq: set `LLM_PROVIDER=groq`, `LLM_API_KEY` and `LLM_MODEL` (default recommendation `openai/gpt-oss-120b`; list models with GET https://api.groq.com/openai/v1/models) in `.env` (optionally `LLM_PRICE_IN_PER_M` / `LLM_PRICE_OUT_PER_M` to get a cost estimate; none is assumed).

Limitations: confidence is an uncalibrated heuristic; the approved-supplier list must be configured by an admin (no data source otherwise); amount rules are USD-only (no FX source); category-specific rules (for example "IT hardware needs IT review") are left to the LLM stage and the human; the injection scan is a heuristic.

## Setup

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -e ".[dev]"   # Windows; use .venv/bin/python on macOS/Linux
cp .env.example .env                               # then set DATABASE_URL (Supabase session pooler string)
.venv/Scripts/python -m uvicorn app.main:app --reload
.venv/Scripts/python -m pytest
```

If you change `app/db/models.py`, regenerate the SQL with `python scripts/gen_ddl.py` (a unit test fails if it is stale).

## Verified against the live Supabase database

`alembic upgrade head` (no-op at revision `0001`), `/health/ready`, the audit-log chain, and document ingestion/upload (integration tests run inside a transaction that is rolled back; the database is left empty).
